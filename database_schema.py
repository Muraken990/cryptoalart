#!/usr/bin/env python3
"""
CryptoAlert Database Schema and Management - 下落率アラート対応版
データベース設計とテーブル管理
"""

import sqlite3
import hashlib
import secrets
import requests
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import json

DATABASE_FILE = "crypto_alerts.db"
BINANCE_API_URL = "https://api.binance.com/api/v3"

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
            
            # アラートテーブル（下落率対応）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    symbol VARCHAR(20) NOT NULL,
                    base_symbol VARCHAR(10) NOT NULL,
                    threshold_percent DECIMAL(5,2) NOT NULL,
                    alert_type VARCHAR(10) NOT NULL DEFAULT 'rise',
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
            
            # 既存テーブルにalert_typeカラムを追加（存在しない場合）
            try:
                conn.execute("ALTER TABLE alerts ADD COLUMN alert_type VARCHAR(10) DEFAULT 'rise'")
                print("✅ alert_typeカラムを追加しました")
            except sqlite3.OperationalError:
                # カラムが既に存在する場合
                pass
            
            # アラート履歴テーブル（下落率対応）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id INTEGER NOT NULL,
                    user_email VARCHAR(255) NOT NULL,
                    symbol VARCHAR(20) NOT NULL,
                    threshold_percent DECIMAL(5,2) NOT NULL,
                    alert_type VARCHAR(10) NOT NULL DEFAULT 'rise',
                    base_price DECIMAL(15,8) NOT NULL,
                    trigger_price DECIMAL(15,8) NOT NULL,
                    price_change DECIMAL(5,2) NOT NULL,
                    triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    email_sent BOOLEAN DEFAULT 0,
                    email_sent_at TIMESTAMP,
                    FOREIGN KEY (alert_id) REFERENCES alerts (id) ON DELETE CASCADE
                )
            """)
            
            # 既存履歴テーブルにalert_typeカラムを追加
            try:
                conn.execute("ALTER TABLE alert_history ADD COLUMN alert_type VARCHAR(10) DEFAULT 'rise'")
                print("✅ alert_history.alert_typeカラムを追加しました")
            except sqlite3.OperationalError:
                pass
            
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_type ON alerts(alert_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_price_history_symbol ON price_history(symbol, recorded_at)")
            
            # 初期システム設定
            self._insert_default_config(conn)
            
            conn.commit()
            print("✅ データベース初期化完了（下落率アラート対応）")
    
    def _insert_default_config(self, conn):
        """デフォルト設定を挿入"""
        default_configs = [
            ('free_daily_limit', '5'),
            ('paid_daily_limit', '100'),
            ('max_alerts_per_user', '20'),
            ('min_threshold_percent', '0.1'),
            ('max_threshold_percent', '50.0'),
            ('check_interval_seconds', '60'),
            ('email_cooldown_minutes', '5'),
            ('min_fall_threshold', '-50.0'),  # 最大下落率
            ('max_rise_threshold', '50.0')    # 最大上昇率
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
    
    def create_alert(self, email: str, symbol: str, threshold_percent: float, alert_type: str = 'rise') -> Dict:
        """新しいアラートを作成（上昇・下落対応）"""
        user_id = self.get_or_create_user(email)
        
        # アラートタイプ検証
        if alert_type not in ['rise', 'fall']:
            raise ValueError(f"無効なアラートタイプ: {alert_type} (rise または fall を指定してください)")
        
        # 閾値検証
        if alert_type == 'rise':
            if threshold_percent <= 0 or threshold_percent > 50:
                raise ValueError("上昇率は0.1%から50%の間で設定してください")
        else:  # fall
            if threshold_percent >= 0 or threshold_percent < -50:
                raise ValueError("下落率は-0.1%から-50%の間で設定してください")
        
        # シンボル正規化
        original_symbol = symbol
        symbol = symbol.upper()
        if not symbol.endswith('USDT'):
            symbol += 'USDT'
        base_symbol = symbol.replace('USDT', '')
        
        # シンボル有効性チェック
        print(f"🔍 シンボル検証中: {symbol}")
        if not self.validate_symbol(symbol):
            raise ValueError(f"無効なシンボル: {original_symbol} ({symbol})")
        
        # 現在価格を取得
        print(f"📡 現在価格取得中: {symbol}")
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
                (user_id, symbol, base_symbol, threshold_percent, alert_type, base_price, 
                 current_price, alert_token, last_checked)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (user_id, symbol, base_symbol, threshold_percent, alert_type, base_price, base_price, alert_token))
            
            alert_id = cursor.lastrowid
            conn.commit()
            
            # 目標価格計算
            target_price = base_price * (1 + threshold_percent/100)
            
            alert_direction = "上昇" if alert_type == 'rise' else "下落"
            print(f"✅ {alert_direction}アラート作成: {symbol} {threshold_percent:+.2f}% (ID: {alert_id})")
            print(f"📊 基準価格: ${base_price:,.6f}")
            print(f"🎯 目標価格: ${target_price:,.6f}")
            
            return {
                'alert_id': alert_id,
                'symbol': symbol,
                'base_symbol': base_symbol,
                'threshold_percent': threshold_percent,
                'alert_type': alert_type,
                'base_price': base_price,
                'target_price': target_price,
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
                alert = dict(row)
                # alert_typeがNullの場合のデフォルト値設定
                if not alert.get('alert_type'):
                    alert['alert_type'] = 'rise'
                alerts.append(alert)
            
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
                alert = dict(row)
                if not alert.get('alert_type'):
                    alert['alert_type'] = 'rise'
                alerts.append(alert)
            
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
    
    def trigger_alert(self, alert_id: int, trigger_price: float, price_change: float, alert_type: str = 'rise'):
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
                    (alert_id, user_email, symbol, threshold_percent, alert_type,
                     base_price, trigger_price, price_change)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (alert_id, alert_data[13], alert_data[2], alert_data[4], alert_type,
                      alert_data[6], trigger_price, price_change))
            
            conn.commit()
            direction = "上昇" if alert_type == 'rise' else "下落"
            print(f"🚨 {direction}アラートトリガー: ID {alert_id}, 価格変動: {price_change:+.2f}%")
    
    def mark_email_sent(self, alert_id: int):
        """メール送信完了をマーク"""
        with sqlite3.connect(self.db_file) as conn:
            conn.execute("""
                UPDATE alert_history 
                SET email_sent = 1, email_sent_at = CURRENT_TIMESTAMP
                WHERE alert_id = ? AND email_sent = 0
            """, (alert_id,))
            conn.commit()
    
    def check_alert_condition(self, alert: Dict) -> Optional[Dict]:
        """アラート条件をチェック（上昇・下落対応）"""
        symbol = alert['symbol']
        base_price = float(alert['base_price'])
        threshold_percent = float(alert['threshold_percent'])
        alert_type = alert.get('alert_type', 'rise')
        
        # 現在価格取得
        current_price = self._get_current_price(symbol)
        if current_price is None:
            return None
        
        # 価格変動率計算
        price_change = ((current_price - base_price) / base_price) * 100
        
        # アラート条件チェック
        triggered = False
        if alert_type == 'rise':
            # 上昇アラート: 価格変動率が閾値以上
            triggered = price_change >= threshold_percent
        else:  # fall
            # 下落アラート: 価格変動率が閾値以下
            triggered = price_change <= threshold_percent
        
        if triggered:
            return {
                'alert_id': alert['id'],
                'symbol': symbol,
                'base_price': base_price,
                'current_price': current_price,
                'price_change': price_change,
                'threshold_percent': threshold_percent,
                'alert_type': alert_type,
                'user_email': alert['email'],
                'triggered': True
            }
        
        # 価格のみ更新
        self.update_alert_price(alert['id'], current_price)
        
        return {
            'alert_id': alert['id'],
            'symbol': symbol,
            'current_price': current_price,
            'price_change': price_change,
            'alert_type': alert_type,
            'triggered': False
        }
    
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
            
            # アラートタイプ別統計
            cursor = conn.execute("""
                SELECT alert_type, COUNT(*) 
                FROM alerts 
                WHERE status = 'active' 
                GROUP BY alert_type
            """)
            alert_types = dict(cursor.fetchall())
            stats['rise_alerts'] = alert_types.get('rise', 0)
            stats['fall_alerts'] = alert_types.get('fall', 0)
            
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
        """Binance APIから現在価格を取得"""
        try:
            url = f"{BINANCE_API_URL}/ticker/price"
            params = {'symbol': symbol}
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            price = float(data['price'])
            
            print(f"📊 {symbol}: ${price:,.6f}")
            return price
            
        except requests.exceptions.RequestException as e:
            print(f"❌ API接続エラー ({symbol}): {e}")
            return None
        except (KeyError, ValueError) as e:
            print(f"❌ データ解析エラー ({symbol}): {e}")
            return None
        except Exception as e:
            print(f"❌ 予期しないエラー ({symbol}): {e}")
            return None
    
    def get_binance_symbol_info(self, symbol: str) -> Optional[Dict]:
        """Binance APIからシンボル情報を取得"""
        try:
            url = f"{BINANCE_API_URL}/exchangeInfo"
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            
            for symbol_info in data['symbols']:
                if symbol_info['symbol'] == symbol:
                    return {
                        'symbol': symbol_info['symbol'],
                        'status': symbol_info['status'],
                        'baseAsset': symbol_info['baseAsset'],
                        'quoteAsset': symbol_info['quoteAsset'],
                        'isSpotTradingAllowed': symbol_info['isSpotTradingAllowed']
                    }
            
            return None
            
        except Exception as e:
            print(f"⚠️ シンボル情報取得エラー: {e}")
            return None
    
    def validate_symbol(self, symbol: str) -> bool:
        """シンボルが有効かチェック"""
        symbol_info = self.get_binance_symbol_info(symbol)
        
        if not symbol_info:
            return False
        
        return (symbol_info['status'] == 'TRADING' and 
                symbol_info['isSpotTradingAllowed'] and
                symbol_info['quoteAsset'] == 'USDT')
    
    def get_24hr_stats(self, symbol: str) -> Optional[Dict]:
        """24時間統計を取得"""
        try:
            url = f"{BINANCE_API_URL}/ticker/24hr"
            params = {'symbol': symbol}
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            return {
                'symbol': data['symbol'],
                'priceChange': float(data['priceChange']),
                'priceChangePercent': float(data['priceChangePercent']),
                'weightedAvgPrice': float(data['weightedAvgPrice']),
                'prevClosePrice': float(data['prevClosePrice']),
                'lastPrice': float(data['lastPrice']),
                'bidPrice': float(data['bidPrice']),
                'askPrice': float(data['askPrice']),
                'openPrice': float(data['openPrice']),
                'highPrice': float(data['highPrice']),
                'lowPrice': float(data['lowPrice']),
                'volume': float(data['volume']),
                'quoteVolume': float(data['quoteVolume']),
                'count': int(data['count'])
            }
            
        except Exception as e:
            print(f"⚠️ 24時間統計取得エラー ({symbol}): {e}")
            return None

def main():
    """データベース初期化とテスト"""
    print("🗄️ CryptoAlert Database 初期化（上昇・下落アラート対応版）")
    print("=" * 60)
    
    # データベース初期化
    db = AlertDatabase()
    
    # Binance API接続テスト
    print("\n📡 Binance API接続テスト...")
    test_symbols = ['BTCUSDT', 'ETHUSDT', 'ADAUSDT']
    
    for symbol in test_symbols:
        price = db._get_current_price(symbol)
        if price:
            print(f"✅ {symbol}: ${price:,.2f}")
        else:
            print(f"❌ {symbol}: 価格取得失敗")
    
    # テストデータ作成
    print("\n📝 テストアラート作成中...")
    
    try:
        # 上昇アラート
        alert1 = db.create_alert("test@example.com", "BTC", 5.0, "rise")
        time.sleep(1)
        
        # 下落アラート
        alert2 = db.create_alert("test@example.com", "ETH", -3.0, "fall")
        time.sleep(1)
        
        # 混合アラート
        alert3 = db.create_alert("user2@example.com", "ADA", 10.0, "rise")
        alert4 = db.create_alert("user2@example.com", "DOT", -5.0, "fall")
        
        print("\n📊 アクティブアラート一覧:")
        active_alerts = db.get_active_alerts()
        for alert in active_alerts:
            current_price = float(alert['current_price'])
            base_price = float(alert['base_price'])
            change = ((current_price - base_price) / base_price) * 100
            alert_type = alert.get('alert_type', 'rise')
            direction = "上昇" if alert_type == 'rise' else "下落"
            
            print(f"  • {alert['symbol']}: {direction} {alert['threshold_percent']:+.2f}% 目標")
            print(f"    現在: ${current_price:,.6f} ({change:+.2f}%) - {alert['email']}")
        
        print("\n🔍 アラート条件チェックテスト...")
        for alert in active_alerts[:2]:
            result = db.check_alert_condition(alert)
            if result:
                status = "🚨 発火!" if result['triggered'] else "⏳ 待機中"
                alert_type = result.get('alert_type', 'rise')
                direction = "上昇" if alert_type == 'rise' else "下落"
                print(f"  • {result['symbol']} ({direction}): {result['price_change']:+.2f}% {status}")
        
        print("\n📈 システム統計:")
        stats = db.get_statistics()
        for key, value in stats.items():
            print(f"  • {key}: {value}")
        
        print("\n✅ 上昇・下落アラート対応テスト完了")
        
    except Exception as e:
        print(f"❌ エラー: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()