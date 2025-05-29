#!/usr/bin/env python3
"""
CryptoAlert Monitor Process - サービス代行型
ユーザーはパスワード不要、サービス側固定アカウントからメール送信

使用方法:
    # 基本実行
    python monitor.py
    
    # 設定テスト
    python monitor.py --test-email
    
    # デバッグモード
    python monitor.py --debug

サービス側環境変数設定:
    export SERVICE_GMAIL="alerts@your-domain.com"
    export SERVICE_GMAIL_PASS="your_service_app_password"
    export SERVICE_NAME="CryptoAlert Service"
"""

import os
import time
import smtplib
import argparse
from datetime import datetime, timedelta
from typing import Dict, List
import signal
import sys

# emailモジュールの安全なインポート
import email.mime.text
import email.mime.multipart

# 自作データベースクラスをインポート
from database_schema import AlertDatabase

class CryptoAlertService:
    """サービス代行型アラートシステム"""
    
    def __init__(self, check_interval: int = 60, debug: bool = False):
        self.db = AlertDatabase()
        self.check_interval = check_interval
        self.debug = debug
        self.running = True
        self.service_config = self._load_service_config()
        
        # 送信統計
        self.stats = {
            'emails_sent': 0,
            'alerts_triggered': 0,
            'errors': 0,
            'start_time': datetime.now()
        }
        
        # シグナルハンドラー設定（Ctrl+Cで停止）
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _load_service_config(self) -> Dict:
        """サービス側メール設定を読み込み"""
        config = {
            'smtp_server': 'smtp.gmail.com',
            'smtp_port': 587,
            'service_email': os.getenv('SERVICE_GMAIL', 'alerts@cryptoalert.com'),
            'service_password': os.getenv('SERVICE_GMAIL_PASS', ''),
            'service_name': os.getenv('SERVICE_NAME', 'CryptoAlert Service'),
            'website_url': 'https://cryptoalert.com',  # 将来のウェブサイト
            'support_email': 'support@cryptoalert.com'
        }
        
        # 設定チェック
        if not config['service_password']:
            print("⚠️ 警告: SERVICE_GMAIL_PASS 環境変数が設定されていません")
        
        return config
    
    def _signal_handler(self, signum, frame):
        """シグナルハンドラー（停止処理）"""
        print(f"\n🛑 監視停止シグナル受信 (signal: {signum})")
        self.running = False
    
    def create_alert_email(self, alert_data: Dict) -> Dict:
        """アラートメールの内容を作成"""
        
        # 件名
        subject = f"🚨 {alert_data['base_symbol']} Price Alert - {alert_data['price_change']:+.2f}%"
        
        # 本文作成
        body_text = f"""
🎯 CryptoAlert - Price Alert Triggered

Hi there! 👋

Great news! Your crypto price alert has been triggered:

📊 ALERT DETAILS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Symbol: {alert_data['symbol']} ({alert_data['base_symbol']}/USDT)
• Current Price: ${alert_data['current_price']:,.6f}
• Base Price: ${alert_data['base_price']:,.6f}
• Price Change: {alert_data['price_change']:+.2f}%
• Your Threshold: {alert_data['threshold_percent']:+.2f}%
• Triggered: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🔥 YOUR PREDICTION WAS RIGHT!
The price moved as you expected. Time to take action?
"""
        
        # 24時間統計を追加
        stats = self.db.get_24hr_stats(alert_data['symbol'])
        if stats:
            body_text += f"""

📈 24-HOUR MARKET DATA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• 24h Change: {stats['priceChangePercent']:+.2f}%
• 24h High: ${stats['highPrice']:,.6f}
• 24h Low: ${stats['lowPrice']:,.6f}
• 24h Volume: {stats['quoteVolume']:,.0f} USDT
• Trades Count: {stats['count']:,}
"""
        
        body_text += f"""

💡 WHAT'S NEXT?
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ This alert has been automatically deactivated
🔄 Create new alerts anytime at {self.service_config['website_url']}
📊 Consider setting alerts for other price levels
⚡ Set up alerts for different cryptocurrencies

───────────────────────────────────────────────────────────────

Best regards,
{self.service_config['service_name']} 🚀

📧 Alert sent to: {alert_data['user_email']}
🌐 Website: {self.service_config['website_url']}
💬 Support: {self.service_config['support_email']}

───────────────────────────────────────────────────────────────

🔗 MANAGE YOUR ALERTS
• Stop this alert: {self.service_config['website_url']}/stop?token={alert_data.get('alert_token', '')}
• Unsubscribe all: {self.service_config['website_url']}/unsubscribe?token={alert_data.get('unsubscribe_token', '')}

⚠️ DISCLAIMER
This is not financial advice. Always do your own research.
Cryptocurrency investments carry high risk.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{self.service_config['service_name']} | Automated Crypto Alerts
"""
        
        return {
            'subject': subject,
            'body': body_text,
            'from_email': self.service_config['service_email'],
            'from_name': self.service_config['service_name'],
            'to_email': alert_data['user_email']
        }
    
    def send_service_email(self, alert_data: Dict) -> bool:
        """サービス側固定アカウントからメール送信"""
        try:
            # メール内容作成
            email_content = self.create_alert_email(alert_data)
            
            # MIMEメッセージ作成
            msg = email.mime.multipart.MIMEMultipart()
            msg['From'] = f"{email_content['from_name']} <{email_content['from_email']}>"
            msg['To'] = email_content['to_email']
            msg['Subject'] = email_content['subject']
            msg['Reply-To'] = self.service_config['support_email']
            
            # 本文添付
            msg.attach(email.mime.text.MIMEText(email_content['body'], 'plain', 'utf-8'))
            
            # SMTP送信（サービス側アカウント使用）
            with smtplib.SMTP(self.service_config['smtp_server'], self.service_config['smtp_port']) as server:
                server.starttls()
                server.login(
                    self.service_config['service_email'],
                    self.service_config['service_password']
                )
                server.send_message(msg)
            
            print(f"✅ メール送信成功: {alert_data['user_email']} ({alert_data['symbol']})")
            self.stats['emails_sent'] += 1
            return True
            
        except Exception as e:
            print(f"❌ メール送信エラー: {e}")
            self.stats['errors'] += 1
            if self.debug:
                import traceback
                traceback.print_exc()
            return False
    
    def test_service_email(self) -> bool:
        """サービスメール設定をテスト"""
        print("🧪 サービスメール設定テスト中...")
        print(f"   サービスアカウント: {self.service_config['service_email']}")
        print(f"   サービス名: {self.service_config['service_name']}")
        
        if not self.service_config['service_password']:
            print("❌ SERVICE_GMAIL_PASS 環境変数が設定されていません")
            print("\n💡 設定方法:")
            print("export SERVICE_GMAIL='alerts@your-domain.com'")
            print("export SERVICE_GMAIL_PASS='your_app_password'")
            return False
        
        try:
            # テスト用アラートデータ
            test_alert = {
                'symbol': 'BTCUSDT',
                'base_symbol': 'BTC',
                'current_price': 55000.0,
                'base_price': 50000.0, 
                'price_change': 10.0,
                'threshold_percent': 8.0,
                'user_email': self.service_config['service_email'],  # 自分宛にテスト
                'alert_token': 'test_alert_token',
                'unsubscribe_token': 'test_unsubscribe_token'
            }
            
            # テストメール送信
            result = self.send_service_email(test_alert)
            
            if result:
                print("✅ テストメール送信成功！")
                print(f"📧 送信先: {test_alert['user_email']}")
                print("📝 メールボックスを確認してください")
            
            return result
            
        except Exception as e:
            print(f"❌ テストメール送信失敗: {e}")
            return False
    
    def process_alert(self, alert: Dict) -> bool:
        """個別アラートを処理"""
        try:
            if self.debug:
                print(f"🔍 処理中: {alert['symbol']} (ID: {alert['id']}) → {alert['email']}")
            
            # アラート条件チェック
            result = self.db.check_alert_condition(alert)
            if not result:
                if self.debug:
                    print(f"   ⚠️ 価格取得失敗: {alert['symbol']}")
                return False
            
            if result['triggered']:
                print(f"🚨 アラート発火! {result['symbol']}: {result['price_change']:+.2f}% → {result['user_email']}")
                
                # メール送信データ準備
                email_data = {
                    **result,
                    'base_symbol': alert['base_symbol'],
                    'alert_token': alert.get('alert_token', ''),
                    'unsubscribe_token': alert.get('unsubscribe_token', '')
                }
                
                # サービス側からメール送信
                email_sent = self.send_service_email(email_data)
                
                # データベース更新
                self.db.trigger_alert(
                    alert['id'], 
                    result['current_price'], 
                    result['price_change']
                )
                
                if email_sent:
                    self.db.mark_email_sent(alert['id'])
                
                self.stats['alerts_triggered'] += 1
                return True
            else:
                if self.debug:
                    print(f"   ⏳ 待機中: {result['symbol']} ({result['price_change']:+.2f}%)")
                return False
                
        except Exception as e:
            print(f"❌ アラート処理エラー (ID: {alert.get('id', 'unknown')}): {e}")
            self.stats['errors'] += 1
            if self.debug:
                import traceback
                traceback.print_exc()
            return False
    
    def run_monitor_cycle(self) -> Dict:
        """監視サイクルを1回実行"""
        cycle_start = time.time()
        
        # アクティブアラート取得
        active_alerts = self.db.get_active_alerts()
        
        if not active_alerts:
            if self.debug:
                print("📝 アクティブなアラートはありません")
            return {'processed': 0, 'triggered': 0, 'errors': 0}
        
        print(f"🔄 監視中: {len(active_alerts)}件のアラート")
        
        # 統計
        cycle_stats = {'processed': 0, 'triggered': 0, 'errors': 0}
        
        # 各アラートを処理
        for alert in active_alerts:
            try:
                triggered = self.process_alert(alert)
                cycle_stats['processed'] += 1
                if triggered:
                    cycle_stats['triggered'] += 1
                    
                # API制限対応（0.5秒間隔）
                time.sleep(0.5)
                
            except Exception as e:
                cycle_stats['errors'] += 1
                print(f"⚠️ アラート処理エラー: {e}")
        
        cycle_time = time.time() - cycle_start
        
        if self.debug or cycle_stats['triggered'] > 0:
            print(f"📊 サイクル完了: 処理={cycle_stats['processed']}, 発火={cycle_stats['triggered']}, エラー={cycle_stats['errors']}, 時間={cycle_time:.1f}秒")
        
        return cycle_stats
    
    def display_service_status(self):
        """サービス状態を表示"""
        uptime = datetime.now() - self.stats['start_time']
        db_stats = self.db.get_statistics()
        
        print("\n" + "="*60)
        print("📊 CryptoAlert Service Status")
        print("="*60)
        print(f"🚀 サービス名: {self.service_config['service_name']}")
        print(f"📧 送信アカウント: {self.service_config['service_email']}")
        print(f"⏰ 稼働時間: {uptime}")
        print(f"📈 総メール送信: {self.stats['emails_sent']}")
        print(f"🚨 総アラート発火: {self.stats['alerts_triggered']}")
        print(f"❌ エラー数: {self.stats['errors']}")
        print(f"👥 アクティブユーザー: {db_stats['active_users']}")
        print(f"⚡ アクティブアラート: {db_stats['active_alerts']}")
        print("="*60)
    
    def run(self):
        """メイン監視ループ"""
        print("🚀 CryptoAlert Service Monitor 開始")
        print("=" * 60)
        print("📋 サービス代行型アラートシステム")
        print(f"📊 チェック間隔: {self.check_interval}秒")
        print(f"📧 サービス送信者: {self.service_config['service_email']}")
        print(f"🏢 サービス名: {self.service_config['service_name']}")
        print(f"🔧 デバッグモード: {'ON' if self.debug else 'OFF'}")
        print("📝 Ctrl+C で停止")
        print("=" * 60)
        
        # 初回統計表示
        db_stats = self.db.get_statistics()
        print(f"📈 初期状態: {db_stats['active_alerts']}件のアラート監視中")
        print(f"👥 登録ユーザー: {db_stats['active_users']}名")
        print()
        
        cycle_count = 0
        
        try:
            while self.running:
                cycle_count += 1
                
                if self.debug:
                    print(f"\n--- サイクル {cycle_count} ({datetime.now().strftime('%H:%M:%S')}) ---")
                
                # 監視サイクル実行
                cycle_stats = self.run_monitor_cycle()
                
                # 1時間ごとに統計報告
                if cycle_count % (3600 // self.check_interval) == 0:
                    self.display_service_status()
                
                # 待機
                if self.running:
                    time.sleep(self.check_interval)
                
        except KeyboardInterrupt:
            print("\n🛑 キーボード割り込み受信")
        except Exception as e:
            print(f"\n❌ 予期しないエラー: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
        finally:
            self.display_service_status()
            print(f"\n📊 監視終了統計:")
            print(f"   • 総サイクル数: {cycle_count}")
            print(f"   • 稼働時間: {cycle_count * self.check_interval / 60:.1f}分")
            print("✅ CryptoAlert Service 終了")

def parse_arguments():
    """コマンドライン引数解析"""
    parser = argparse.ArgumentParser(description='CryptoAlert Service Monitor')
    
    parser.add_argument('--interval', type=int, default=60,
                       help='チェック間隔（秒）デフォルト: 60秒')
    parser.add_argument('--debug', action='store_true',
                       help='デバッグモードを有効化')
    parser.add_argument('--test-email', action='store_true',
                       help='サービスメール送信テストを実行')
    
    return parser.parse_args()

def main():
    args = parse_arguments()
    
    # サービス監視プロセス初期化
    service = CryptoAlertService(
        check_interval=args.interval,
        debug=args.debug
    )
    
    # メールテストモード
    if args.test_email:
        print("🧪 サービスメール送信テストモード")
        if service.test_service_email():
            print("✅ サービスメール設定テスト成功")
        else:
            print("❌ サービスメール設定テスト失敗")
        return
    
    # メイン監視開始
    service.run()

if __name__ == "__main__":
    main()