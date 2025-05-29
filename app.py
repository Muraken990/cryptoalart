#!/usr/bin/env python3
"""
CryptoAlert Web Application - 下落率アラート対応版
FlaskベースのWeb UI + REST API

使用方法:
    pip install flask flask-cors
    python app.py
    
    ブラウザで http://localhost:8000 にアクセス
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_cors import CORS
import os
import json
from datetime import datetime, timedelta
import requests
from database_schema import AlertDatabase

app = Flask(__name__)
app.secret_key = os.urandom(24)
CORS(app)

# データベース初期化
db = AlertDatabase()

@app.route('/')
def index():
    """メインページ"""
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    """ダッシュボード"""
    return render_template('dashboard.html')

@app.route('/create')
def create_alert_page():
    """アラート作成ページ"""
    return render_template('create_alert.html')

# ==================== REST API ====================

@app.route('/api/alerts', methods=['POST'])
def create_alert():
    """アラート作成API（上昇・下落対応）"""
    try:
        data = request.get_json()
        
        # 入力検証
        required_fields = ['email', 'symbol', 'threshold']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'{field} is required'}), 400
        
        email = data['email'].strip().lower()
        symbol = data['symbol'].strip().upper()
        threshold = float(data['threshold'])
        alert_type = data.get('alert_type', 'rise').lower()  # 新しいパラメータ
        
        # バリデーション
        if not email or '@' not in email:
            return jsonify({'error': 'Invalid email address'}), 400
        
        # アラートタイプ検証
        if alert_type not in ['rise', 'fall']:
            return jsonify({'error': 'Alert type must be "rise" or "fall"'}), 400
        
        # 閾値検証（アラートタイプ別）
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

@app.route('/api/alerts/<email>')
def get_user_alerts(email):
    """ユーザーのアラート一覧取得"""
    try:
        alerts = db.get_user_alerts(email.lower().strip())
        
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
def stop_alert(alert_token):
    """アラート停止"""
    try:
        success = db.deactivate_alert(alert_token)
        if success:
            return jsonify({
                'success': True,
                'message': 'Alert stopped successfully'
            })
        else:
            return jsonify({'error': 'Alert not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/status')
def get_status():
    """システム状態取得"""
    try:
        stats = db.get_statistics()
        
        # 監視プロセス状態確認（改善版）
        monitor_status = "Unknown"
        try:
            # 最近のアラート更新時間をチェック
            active_alerts = db.get_active_alerts()
            if active_alerts:
                # 直近2分以内の更新があれば稼働中（より厳密に）
                recent_activity = any(
                    alert.get('last_checked') and 
                    datetime.now() - datetime.fromisoformat(alert['last_checked']) < timedelta(minutes=2)
                    for alert in active_alerts
                )
                monitor_status = "Running" if recent_activity else "Stopped"
            else:
                monitor_status = "No Alerts"
        except Exception as status_error:
            print(f"⚠️ 監視状態確認エラー: {status_error}")
            monitor_status = "Unknown"
        
        return jsonify({
            'success': True,
            'status': {
                'database': 'Connected',
                'monitor': monitor_status,
                'uptime': '24/7',
                'version': '1.1.0'  # バージョンアップ
            },
            'statistics': stats
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/symbols')
def get_symbols():
    """対応銘柄一覧"""
    try:
        # 人気銘柄のリスト
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

@app.route('/api/test-alerts', methods=['POST'])
def create_test_alerts():
    """テスト用アラート一括作成"""
    if not app.debug:
        return jsonify({'error': 'Test endpoints only available in debug mode'}), 403
    
    try:
        test_alerts = [
            {'email': 'test@example.com', 'symbol': 'BTC', 'threshold': 5.0, 'type': 'rise'},
            {'email': 'test@example.com', 'symbol': 'ETH', 'threshold': -3.0, 'type': 'fall'},
            {'email': 'demo@example.com', 'symbol': 'ADA', 'threshold': 8.0, 'type': 'rise'},
            {'email': 'demo@example.com', 'symbol': 'DOT', 'threshold': -5.0, 'type': 'fall'}
        ]
        
        created_alerts = []
        for alert_data in test_alerts:
            try:
                alert = db.create_alert(
                    alert_data['email'], 
                    alert_data['symbol'], 
                    alert_data['threshold'],
                    alert_data['type']
                )
                created_alerts.append(alert)
            except Exception as e:
                print(f"テストアラート作成失敗: {e}")
        
        return jsonify({
            'success': True,
            'message': f'{len(created_alerts)}件のテストアラートを作成しました',
            'alerts': created_alerts
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== メイン実行 ====================

if __name__ == '__main__':
    # 開発環境の設定
    print("🚀 CryptoAlert Web Application Starting... (v1.1.0)")
    print("=" * 50)
    print("📡 Local URL: http://localhost:8000")
    print("🔧 Debug Mode: ON")
    print("📊 Database: SQLite")
    print("📧 Email Service: Gmail SMTP")
    print("📈 New Features: 上昇・下落アラート対応")
    print("=" * 50)
    
    # データベース初期化確認
    try:
        stats = db.get_statistics()
        print(f"✅ Database Connected:")
        print(f"   • アクティブアラート: {stats['active_alerts']}")
        print(f"   • 上昇アラート: {stats.get('rise_alerts', 0)}")
        print(f"   • 下落アラート: {stats.get('fall_alerts', 0)}")
        print(f"   • 登録ユーザー: {stats['active_users']}")
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