#!/usr/bin/env python3
"""
CryptoAlert Web Application - 認証機能対応版
FlaskベースのWeb UI + REST API

使用方法:
    pip install flask flask-cors flask-login bcrypt
    python app.py
    
    ブラウザで http://localhost:8000 にアクセス
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from flask_cors import CORS
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import os
import json
from datetime import datetime, timedelta
import requests
from database_schema import AlertDatabase, User

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', os.urandom(24))
CORS(app)

# Flask-Login設定
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'ログインが必要です。'
login_manager.login_message_category = 'info'

# データベース初期化
db = AlertDatabase()

@login_manager.user_loader
def load_user(user_id):
    """Flask-Login用のユーザーローダー"""
    return db.get_user_by_id(int(user_id))

# ==================== 認証ルート ====================

@app.route('/auth/register', methods=['GET', 'POST'])
def register():
    """ユーザー登録"""
    if request.method == 'POST':
        try:
            data = request.get_json() if request.is_json else request.form
            
            email = data.get('email', '').strip().lower()
            password = data.get('password', '')
            
            # 入力検証
            if not email or '@' not in email:
                raise ValueError('有効なメールアドレスを入力してください')
            
            if len(password) < 6:
                raise ValueError('パスワードは6文字以上で設定してください')
            
            # ユーザー登録
            user_data = db.register_user(email, password)
            
            if request.is_json:
                return jsonify({
                    'success': True,
                    'message': 'アカウント作成が完了しました',
                    'user': user_data
                }), 201
            else:
                flash('アカウント作成が完了しました。ログインしてください。', 'success')
                return redirect(url_for('login'))
        
        except ValueError as e:
            if request.is_json:
                return jsonify({'error': str(e)}), 400
            else:
                flash(str(e), 'error')
                return render_template('auth/register.html')
        except Exception as e:
            if request.is_json:
                return jsonify({'error': f'登録エラー: {str(e)}'}), 500
            else:
                flash(f'登録エラー: {str(e)}', 'error')
                return render_template('auth/register.html')
    
    return render_template('auth/register.html')

@app.route('/auth/login', methods=['GET', 'POST'])
def login():
    """ユーザーログイン"""
    if request.method == 'POST':
        try:
            data = request.get_json() if request.is_json else request.form
            
            email = data.get('email', '').strip().lower()
            password = data.get('password', '')
            remember = data.get('remember', False)
            
            # 入力検証
            if not email or not password:
                raise ValueError('メールアドレスとパスワードを入力してください')
            
            # 認証
            ip_address = request.remote_addr
            user = db.authenticate_user(email, password, ip_address)
            
            if user:
                login_user(user, remember=remember)
                
                if request.is_json:
                    return jsonify({
                        'success': True,
                        'message': 'ログインしました',
                        'user': {
                            'email': user.email,
                            'id': user.id
                        }
                    })
                else:
                    next_page = request.args.get('next')
                    return redirect(next_page or url_for('dashboard'))
            else:
                raise ValueError('メールアドレスまたはパスワードが間違っています')
        
        except ValueError as e:
            if request.is_json:
                return jsonify({'error': str(e)}), 401
            else:
                flash(str(e), 'error')
                return render_template('auth/login.html')
        except Exception as e:
            if request.is_json:
                return jsonify({'error': f'ログインエラー: {str(e)}'}), 500
            else:
                flash(f'ログインエラー: {str(e)}', 'error')
                return render_template('auth/login.html')
    
    return render_template('auth/login.html')

@app.route('/auth/logout')
@login_required
def logout():
    """ユーザーログアウト"""
    logout_user()
    flash('ログアウトしました', 'info')
    return redirect(url_for('index'))

# ==================== メインページ ====================

@app.route('/')
def index():
    """メインページ"""
    return render_template('index.html')

@app.route('/dashboard')
@login_required
def dashboard():
    """ユーザーダッシュボード（ログイン必須）"""
    try:
        # ユーザーのアラート一覧取得
        user_alerts = db.get_user_alerts(current_user.email)
        
        # 統計情報計算
        total_alerts = len(user_alerts)
        active_alerts = len([a for a in user_alerts if a['status'] == 'active'])
        triggered_alerts = len([a for a in user_alerts if a['status'] == 'triggered'])
        
        # アラートタイプ別集計
        rise_alerts = len([a for a in user_alerts if a.get('alert_type', 'rise') == 'rise' and a['status'] == 'active'])
        fall_alerts = len([a for a in user_alerts if a.get('alert_type', 'rise') == 'fall' and a['status'] == 'active'])
        
        # 今日の発火数
        today = datetime.now().date()
        today_triggered = len([a for a in user_alerts if 
                              a.get('triggered_at') and 
                              datetime.fromisoformat(a['triggered_at']).date() == today])
        
        user_stats = {
            'total_alerts': total_alerts,
            'active_alerts': active_alerts,
            'triggered_alerts': triggered_alerts,
            'rise_alerts': rise_alerts,
            'fall_alerts': fall_alerts,
            'today_triggered': today_triggered
        }
        
        return render_template('dashboard.html', 
                             user=current_user, 
                             alerts=user_alerts,
                             stats=user_stats)
    except Exception as e:
        flash(f'ダッシュボード読み込みエラー: {str(e)}', 'error')
        return redirect(url_for('index'))

@app.route('/create')
@login_required
def create_alert_page():
    """アラート作成ページ（ログイン必須）"""
    return render_template('create_alert.html', user=current_user)

# ==================== REST API ====================

@app.route('/api/alerts', methods=['POST'])
@login_required
def create_alert():
    """アラート作成API（ログイン必須）"""
    try:
        data = request.get_json()
        
        # 入力検証
        required_fields = ['symbol', 'threshold']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'{field} is required'}), 400
        
        # ログインユーザーのメールアドレスを使用
        email = current_user.email
        symbol = data['symbol'].strip().upper()
        threshold = float(data['threshold'])
        alert_type = data.get('alert_type', 'rise').lower()
        
        # バリデーション
        if alert_type not in ['rise', 'fall']:
            return jsonify({'error': 'Alert type must be "rise" or "fall"'}), 400
        
        # 閾値検証
        if alert_type == 'rise':
            if threshold <= 0 or threshold > 50:
                return jsonify({'error': 'Rise threshold must be between 0.1% and 50%'}), 400
        else:  # fall
            if threshold >= 0 or threshold < -50:
                return jsonify({'error': 'Fall threshold must be between -0.1% and -50%'}), 400
        
        # アラート作成
        alert = db.create_alert(email, symbol, threshold, alert_type)
        
        direction = "上昇" if alert_type == 'rise' else "下落"
        return jsonify({
            'success': True,
            'alert': alert,
            'message': f'{direction}アラート作成: {symbol} {threshold:+.2f}%'
        }), 201
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@app.route('/api/alerts')
@login_required
def get_user_alerts_api():
    """ログインユーザーのアラート一覧取得"""
    try:
        alerts = db.get_user_alerts(current_user.email)
        
        # レスポンス用データ整形
        formatted_alerts = []
        for alert in alerts:
            alert_type = alert.get('alert_type', 'rise')
            direction = "上昇" if alert_type == 'rise' else "下落"
            
            formatted_alert = {
                **alert,
                'direction': direction,
                'alert_type_label': direction,
                'threshold_display': f"{alert['threshold_percent']:+.2f}%"
            }
            formatted_alerts.append(formatted_alert)
        
        return jsonify({
            'success': True,
            'alerts': formatted_alerts,
            'count': len(formatted_alerts)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/alerts/<alert_token>', methods=['DELETE'])
@login_required
def delete_alert(alert_token):
    """アラート削除（ログイン必須）"""
    try:
        # アラートの所有者確認
        alerts = db.get_user_alerts(current_user.email)
        user_alert = next((a for a in alerts if a.get('alert_token') == alert_token), None)
        
        if not user_alert:
            return jsonify({'error': 'Alert not found or access denied'}), 404
        
        success = db.deactivate_alert(alert_token)
        if success:
            return jsonify({
                'success': True,
                'message': 'Alert deleted successfully'
            })
        else:
            return jsonify({'error': 'Alert not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/status')
def get_status():
    """システム状態取得（修正版）"""
    try:
        stats = db.get_statistics()
        
        # 監視プロセス状態確認
        monitor_status = "Unknown"
        try:
            active_alerts = db.get_active_alerts()
            if active_alerts:
                recent_activity = any(
                    alert.get('last_checked') and 
                    datetime.now() - datetime.fromisoformat(alert['last_checked']) < timedelta(minutes=5)
                    for alert in active_alerts
                )
                monitor_status = "Running" if recent_activity else "Stopped"
            else:
                monitor_status = "No Alerts"
        except Exception as status_error:
            print(f"⚠️ 監視状態確認エラー: {status_error}")
            monitor_status = "Unknown"
        
        # ユーザー認証状態を安全に取得
        user_authenticated = False
        user_email = None
        if hasattr(current_user, 'is_authenticated'):
            try:
                user_authenticated = current_user.is_authenticated
                if user_authenticated and hasattr(current_user, 'email'):
                    user_email = current_user.email
            except:
                user_authenticated = False
        
        return jsonify({
            'success': True,
            'status': {
                'database': 'Connected',
                'monitor': monitor_status,
                'uptime': '24/7',
                'version': '1.1.0 (Auth)',
                'user_authenticated': user_authenticated,
                'user_email': user_email
            },
            'statistics': stats,
            'server_time': datetime.now().isoformat(),
            'alerts_summary': {
                'active_alerts': stats.get('active_alerts', 0),
                'rise_alerts': stats.get('rise_alerts', 0),
                'fall_alerts': stats.get('fall_alerts', 0),
                'today_triggered': stats.get('today_alerts', 0)
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'server_time': datetime.now().isoformat()
        }), 500

@app.route('/api/symbols')
def get_symbols():
    """対応銘柄一覧"""
    try:
        popular_symbols = [
            {'symbol': 'BTC', 'name': 'Bitcoin', 'pair': 'BTCUSDT'},
            {'symbol': 'ETH', 'name': 'Ethereum', 'pair': 'ETHUSDT'},
            {'symbol': 'ADA', 'name': 'Cardano', 'pair': 'ADAUSDT'},
            {'symbol': 'DOT', 'name': 'Polkadot', 'pair': 'DOTUSDT'},
            {'symbol': 'LINK', 'name': 'Chainlink', 'pair': 'LINKUSDT'},
            {'symbol': 'SOL', 'name': 'Solana', 'pair': 'SOLUSDT'},
            {'symbol': 'MATIC', 'name': 'Polygon', 'pair': 'MATICUSDT'},
            {'symbol': 'AVAX', 'name': 'Avalanche', 'pair': 'AVAXUSDT'},
            {'symbol': 'UNI', 'name': 'Uniswap', 'pair': 'UNIUSDT'},
            {'symbol': 'ATOM', 'name': 'Cosmos', 'pair': 'ATOMUSDT'}
        ]
        
        # 現在価格を取得
        for symbol_info in popular_symbols:
            try:
                price = db._get_current_price(symbol_info['pair'])
                symbol_info['current_price'] = price
            except:
                symbol_info['current_price'] = None
        
        return jsonify({
            'success': True,
            'symbols': popular_symbols
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/alert-types')
def get_alert_types():
    """アラートタイプ一覧取得"""
    try:
        alert_types = [
            {
                'value': 'rise',
                'label': '上昇アラート',
                'description': '価格が指定した%以上上昇したときに通知',
                'icon': '📈',
                'example': '+5% で通知'
            },
            {
                'value': 'fall',
                'label': '下落アラート', 
                'description': '価格が指定した%以上下落したときに通知',
                'icon': '📉',
                'example': '-3% で通知'
            }
        ]
        
        return jsonify({
            'success': True,
            'alert_types': alert_types
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== 既存の非認証ルート（後方互換性） ====================

@app.route('/legacy/alerts/<email>')
def get_user_alerts_legacy(email):
    """従来のアラート一覧取得（後方互換性用）"""
    try:
        alerts = db.get_user_alerts(email.lower().strip())
        
        formatted_alerts = []
        for alert in alerts:
            alert_type = alert.get('alert_type', 'rise')
            direction = "上昇" if alert_type == 'rise' else "下落"
            
            formatted_alert = {
                **alert,
                'direction': direction,
                'alert_type_label': direction,
                'threshold_display': f"{alert['threshold_percent']:+.2f}%"
            }
            formatted_alerts.append(formatted_alert)
        
        return jsonify({
            'success': True,
            'alerts': formatted_alerts,
            'count': len(formatted_alerts),
            'notice': 'このAPIは非推奨です。ログイン機能をご利用ください。'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/legacy/alerts/<alert_token>', methods=['DELETE'])
def stop_alert_legacy(alert_token):
    """従来のアラート停止（後方互換性用）"""
    try:
        success = db.deactivate_alert(alert_token)
        if success:
            return jsonify({
                'success': True,
                'message': 'Alert stopped successfully',
                'notice': 'このAPIは非推奨です。ログイン機能をご利用ください。'
            })
        else:
            return jsonify({'error': 'Alert not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== Webページルート ====================

@app.route('/stop')
def stop_alert_page():
    """アラート停止ページ"""
    token = request.args.get('token')
    if not token:
        flash('Invalid stop link', 'error')
        return redirect(url_for('index'))
    
    try:
        success = db.deactivate_alert(token)
        if success:
            flash('Alert stopped successfully!', 'success')
        else:
            flash('Alert not found or already stopped', 'error')
    except Exception as e:
        flash(f'Error stopping alert: {str(e)}', 'error')
    
    return render_template('stop_alert.html')

@app.route('/unsubscribe')
def unsubscribe_page():
    """配信停止ページ"""
    token = request.args.get('token')
    if not token:
        flash('Invalid unsubscribe link', 'error')
        return redirect(url_for('index'))
    
    try:
        success = db.unsubscribe_user(token)
        if success:
            flash('Successfully unsubscribed from all alerts!', 'success')
        else:
            flash('User not found or already unsubscribed', 'error')
    except Exception as e:
        flash(f'Error unsubscribing: {str(e)}', 'error')
    
    return render_template('unsubscribe.html')

# ==================== エラーハンドラー ====================

@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

# ==================== 開発用機能 ====================

@app.route('/admin')
def admin():
    """管理者ページ（開発用）"""
    if not app.debug:
        return "Admin page only available in debug mode", 403
    
    stats = db.get_statistics()
    active_alerts = db.get_active_alerts()
    
    # アラート情報を拡張
    for alert in active_alerts:
        alert_type = alert.get('alert_type', 'rise')
        alert['direction'] = "上昇" if alert_type == 'rise' else "下落"
        alert['alert_type_label'] = alert['direction']
    
    return render_template('admin.html', 
                         statistics=stats, 
                         alerts=active_alerts)

@app.route('/test')
def test_page():
    """テストページ"""
    if not app.debug:
        return "Test page only available in debug mode", 403
    
    return render_template('test.html')

# ==================== メイン実行 ====================

if __name__ == '__main__':
    # 開発環境の設定
    print("🚀 CryptoAlert Web Application Starting... (v1.1.0 - Auth)")
    print("=" * 50)
    print("📡 Local URL: http://localhost:8000")
    print("🔧 Debug Mode: ON")
    print("📊 Database: SQLite")
    print("📧 Email Service: Gmail SMTP")
    print("🔐 Authentication: Flask-Login + bcrypt")
    print("📈 Features: 上昇・下落アラート + ユーザー認証")
    print("=" * 50)
    
    # データベース初期化確認
    try:
        stats = db.get_statistics()
        print(f"✅ Database Connected:")
        print(f"   • アクティブアラート: {stats['active_alerts']}")
        print(f"   • 上昇アラート: {stats.get('rise_alerts', 0)}")
        print(f"   • 下落アラート: {stats.get('fall_alerts', 0)}")
        print(f"   • 登録ユーザー: {stats.get('registered_users', 0)}")
        print(f"   • 総ユーザー: {stats['active_users']}")
    except Exception as e:
        print(f"⚠️ Database Warning: {e}")
    
    print("🌐 Starting Flask server...")
    print("📝 Press Ctrl+C to stop")
    print()
    
    # Flask開発サーバー起動
    app.run(
        debug=True,
        host='0.0.0.0',
        port=8000,
        threaded=True
    )