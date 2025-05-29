#!/usr/bin/env python3
"""
CryptoAlert Database Schema and Management
データベース設計とテーブル管理
"""

import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import json

DATABASE_FILE = "crypto_alerts.db"

class AlertDatabase:
    def __init__(self, db_file: str = DATABASE_FILE):
        self.db_file = db_file
        self.init_database()
    
    def init_database(self):
        """データベースとテーブルを初期化"""
        with sqlite3.connect(self.db_file) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            
            # ユーザーテーブル
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    email_hash VARCHAR(64) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1,
                    daily_alert_count INTEGER DEFAULT 0,
                    plan VARCHAR(20) DEFAULT 'free',
                    unsubscribe_token VARCHAR(64) UNIQUE
                )
            """)
            
            # アラートテーブル
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    symbol VARCHAR(20) NOT NULL,
                    base_symbol VARCHAR(10) NOT NULL,
                    threshold_percent DECIMAL(5,2) NOT NULL,
                    base_price DECIMAL(15,8) NOT NULL,
                    current_price DECIMAL(15,8),
                    status VARCHAR(20) DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    triggered_at TIMESTAMP,
                    last_checked TIMESTAMP,
                    check_interval INTEGER DEFAULT 60,
                    alert_token VARCHAR(64) UNIQUE,
                    metadata TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            """)
            
            # アラート履歴テーブル
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id INTEGER NOT NULL,
                    user_email VARCHAR(255) NOT NULL,
                    symbol VARCHAR(20) NOT NULL,
                    threshold_percent DECIMAL(5,2) NOT NULL,
                    base_price DECIMAL(15,8) NOT NULL,
                    trigger_price DECIMAL(15,8) NOT NULL,
                    price_change DECIMAL(5,2) NOT NULL,
                    triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    email_sent BOOLEAN DEFAULT 0,
                    email_sent_at TIMESTAMP,
                    FOREIGN KEY (alert_id) REFERENCES alerts (id) ON DELETE CASCADE
                )
            """)
            
            # システム設定テーブル
            conn.execute("""
                CREATE TABLE IF NOT EXISTS system_config (
                    key VARCHAR(100) PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 価格履歴テーブル（オプション：分析用）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol VARCHAR(20) NOT NULL,
                    price DECIMAL(15,8) NOT NULL,
                    volume DECIMAL(20,2),
                    market_cap DECIMAL(20,2),
                    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # インデックス作成
            conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_user_id ON alerts(user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON alerts(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_price_history_symbol ON price_history(symbol, recorded_at)")
            
            # 初期システム設定
            self._insert_default_config(conn)
            
            conn.commit()
            print("✅ データベース初期化完了")
    
    def _insert_default_config(self, conn):
        """デフォルト設定を挿入"""
        default_configs = [
            ('free_daily_limit', '5'),
            ('paid_daily_limit', '100'),
            ('max_alerts_per_user', '20'),
            ('min_threshold_percent', '0.1'),
            ('max_threshold_percent', '50.0'),
            ('check_interval_seconds', '60'),
            ('email_cooldown_minutes', '5')
        ]
        
        for key, value in default_configs:
            conn.execute("""
                INSERT OR IGNORE INTO system_config (key, value) 
                VALUES (?, ?)
            """, (key, value))
    
    def create_user(self, email: str) -> int:
        """新しいユーザーを作成"""
        email = email.lower().strip()
        email_hash = hashlib.sha256(email.encode()).hexdigest()
        unsubscribe_token = secrets.token_urlsafe(32)
        
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.execute("""
                INSERT INTO users (email, email_hash, unsubscribe_token)
                VALUES (?, ?, ?)
            """, (email, email_hash, unsubscribe_token))
            
            user_id = cursor.lastrowid
            conn.commit()
            print(f"✅ ユーザー作成: {email} (ID: {user_id})")
            return user_id
    
    def get_or_create_user(self, email: str) -> int:
        """ユーザーを取得または作成"""
        email = email.lower().strip()
        
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.execute("SELECT id FROM users WHERE email = ?", (email,))
            result = cursor.fetchone()
            
            if result:
                # 既存ユーザーの最終アクティブ時間を更新
                conn.execute("""
                    UPDATE users SET last_active = CURRENT_TIMESTAMP 
                    WHERE email = ?
                """, (email,))
                conn.commit()
                return result[0]
            else:
                return self.create_user(email)
    
    def create_alert(self, email: str, symbol: str, threshold_percent: float) -> Dict:
        """新しいアラートを作成"""
        user_id = self.get_or_create_user(email)
        
        # シンボル正規化
        symbol = symbol.upper()
        if not symbol.endswith('USDT'):
            symbol += 'USDT'
        base_symbol = symbol.replace('USDT', '')
        
        # 現在価格を取得（実際にはBinance APIから取得）
        base_price = self._get_current_price(symbol)
        if base_price is None:
            raise ValueError(f"価格取得失敗: {symbol}")
        
        alert_token = secrets.token_urlsafe(32)
        
        with sqlite3.connect(self.db_file) as conn:
            # 制限チェック
            if not self._check_user_limits(conn, user_id):
                raise ValueError("アラート作成制限に達しています")
            
            cursor = conn.execute("""
                INSERT INTO alerts 
                (user_id, symbol, base_symbol, threshold_percent, base_price, 
                 current_price, alert_token, last_checked)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (user_id, symbol, base_symbol, threshold_percent, base_price, base_price, alert_token))
            
            alert_id = cursor.lastrowid
            conn.commit()
            
            print(f"✅ アラート作成: {symbol} {threshold_percent:+.2f}% (ID: {alert_id})")
            
            return {
                'alert_id': alert_id,
                'symbol': symbol,
                'base_symbol': base_symbol,
                'threshold_percent': threshold_percent,
                'base_price': base_price,
                'alert_token': alert_token,
                'status': 'active'
            }
    
    def get_active_alerts(self) -> List[Dict]:
        """アクティブなアラート一覧を取得"""
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT a.*, u.email, u.unsubscribe_token
                FROM alerts a
                JOIN users u ON a.user_id = u.id
                WHERE a.status = 'active' AND u.is_active = 1
                ORDER BY a.created_at DESC
            """)
            
            alerts = []
            for row in cursor.fetchall():
                alerts.append(dict(row))
            
            return alerts
    
    def get_user_alerts(self, email: str) -> List[Dict]:
        """特定ユーザーのアラート一覧を取得"""
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT a.*, u.email
                FROM alerts a
                JOIN users u ON a.user_id = u.id
                WHERE u.email = ?
                ORDER BY a.created_at DESC
            """, (email.lower().strip(),))
            
            alerts = []
            for row in cursor.fetchall():
                alerts.append(dict(row))
            
            return alerts
    
    def update_alert_price(self, alert_id: int, current_price: float):
        """アラートの現在価格を更新"""
        with sqlite3.connect(self.db_file) as conn:
            conn.execute("""
                UPDATE alerts 
                SET current_price = ?, last_checked = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (current_price, alert_id))
            conn.commit()
    
    def trigger_alert(self, alert_id: int, trigger_price: float, price_change: float):
        """アラートをトリガー状態にする"""
        with sqlite3.connect(self.db_file) as conn:
            # アラートステータス更新
            conn.execute("""
                UPDATE alerts 
                SET status = 'triggered', triggered_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (alert_id,))
            
            # アラート履歴に記録
            cursor = conn.execute("""
                SELECT a.*, u.email
                FROM alerts a
                JOIN users u ON a.user_id = u.id
                WHERE a.id = ?
            """, (alert_id,))
            
            alert_data = cursor.fetchone()
            if alert_data:
                conn.execute("""
                    INSERT INTO alert_history 
                    (alert_id, user_email, symbol, threshold_percent, 
                     base_price, trigger_price, price_change)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (alert_id, alert_data[12], alert_data[2], alert_data[4], 
                      alert_data[5], trigger_price, price_change))
            
            conn.commit()
            print(f"🚨 アラートトリガー: ID {alert_id}, 価格変動: {price_change:+.2f}%")
    
    def mark_email_sent(self, alert_id: int):
        """メール送信完了をマーク"""
        with sqlite3.connect(self.db_file) as conn:
            conn.execute("""
                UPDATE alert_history 
                SET email_sent = 1, email_sent_at = CURRENT_TIMESTAMP
                WHERE alert_id = ? AND email_sent = 0
            """, (alert_id,))
            conn.commit()
    
    def deactivate_alert(self, alert_token: str) -> bool:
        """アラートを無効化"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.execute("""
                UPDATE alerts SET status = 'stopped'
                WHERE alert_token = ? AND status = 'active'
            """, (alert_token,))
            
            conn.commit()
            return cursor.rowcount > 0
    
    def unsubscribe_user(self, unsubscribe_token: str) -> bool:
        """ユーザーを配信停止"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.execute("""
                UPDATE users SET is_active = 0
                WHERE unsubscribe_token = ?
            """, (unsubscribe_token,))
            
            conn.commit()
            return cursor.rowcount > 0
    
    def get_statistics(self) -> Dict:
        """システム統計を取得"""
        with sqlite3.connect(self.db_file) as conn:
            stats = {}
            
            # ユーザー統計
            cursor = conn.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
            stats['active_users'] = cursor.fetchone()[0]
            
            # アラート統計
            cursor = conn.execute("SELECT COUNT(*) FROM alerts WHERE status = 'active'")
            stats['active_alerts'] = cursor.fetchone()[0]
            
            cursor = conn.execute("SELECT COUNT(*) FROM alerts WHERE status = 'triggered'")
            stats['triggered_alerts'] = cursor.fetchone()[0]
            
            # 今日のアラート数
            cursor = conn.execute("""
                SELECT COUNT(*) FROM alert_history 
                WHERE DATE(triggered_at) = DATE('now')
            """)
            stats['today_alerts'] = cursor.fetchone()[0]
            
            return stats
    
    def _check_user_limits(self, conn, user_id: int) -> bool:
        """ユーザーの制限をチェック"""
        # アクティブアラート数チェック
        cursor = conn.execute("""
            SELECT COUNT(*) FROM alerts 
            WHERE user_id = ? AND status = 'active'
        """, (user_id,))
        
        active_count = cursor.fetchone()[0]
        max_alerts = 20  # 設定から取得すべき
        
        return active_count < max_alerts
    
    def _get_current_price(self, symbol: str) -> Optional[float]:
        """現在価格を取得（プレースホルダー）"""
        # 実際にはBinance APIから取得
        # ここではダミー価格を返す
        dummy_prices = {
            'BTCUSDT': 50000.0,
            'ETHUSDT': 3000.0,
            'ADAUSDT': 0.5,
            'DOTUSDT': 8.0
        }
        return dummy_prices.get(symbol, 1.0)

def main():
    """データベース初期化とテスト"""
    print("🗄️ CryptoAlert Database 初期化")
    print("=" * 50)
    
    # データベース初期化
    db = AlertDatabase()
    
    # テストデータ作成
    print("\n📝 テストデータ作成中...")
    
    try:
        # テストアラート作成
        alert1 = db.create_alert("test@example.com", "BTC", 5.0)
        alert2 = db.create_alert("test@example.com", "ETH", 3.0)
        alert3 = db.create_alert("user2@example.com", "ADA", 10.0)
        
        print("\n📊 アクティブアラート一覧:")
        active_alerts = db.get_active_alerts()
        for alert in active_alerts:
            print(f"  • {alert['symbol']}: {alert['threshold_percent']:+.2f}% ({alert['email']})")
        
        print("\n📈 システム統計:")
        stats = db.get_statistics()
        for key, value in stats.items():
            print(f"  • {key}: {value}")
        
        print("\n✅ データベース初期化完了")
        
    except Exception as e:
        print(f"❌ エラー: {e}")

if __name__ == "__main__":
    main()