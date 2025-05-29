#!/usr/bin/env python3
"""
CryptoWatcher - 仮想通貨パターン検出システム（チャート付き）
指定した日数と価格レンジの銘柄を検知し、チャートを表示

使用方法:
    python sideways_detector_with_charts.py --days 7 --range-low -2 --range-high +2
    python sideways_detector_with_charts.py --days 3 --range-low -1 --range-high +1
    python sideways_detector_with_charts.py --days 14 --range-low -5 --range-high +5 --debug
"""

import requests
import pandas as pd
import numpy as np
import time
import argparse
from datetime import datetime, timedelta
import json
import matplotlib
matplotlib.use('TkAgg')  # GUIバックエンドを明示的に指定
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec
import warnings
warnings.filterwarnings('ignore')

BINANCE_API_URL = "https://api.binance.com/api/v3"

# matplotlib設定
plt.style.use('dark_background')
plt.rcParams['figure.facecolor'] = '#1a1a1a'
plt.rcParams['axes.facecolor'] = '#1a1a1a'
plt.rcParams['grid.color'] = '#333333'
plt.rcParams['text.color'] = '#ffffff'
plt.rcParams['axes.labelcolor'] = '#ffffff'
plt.rcParams['xtick.color'] = '#ffffff'
plt.rcParams['ytick.color'] = '#ffffff'

def parse_arguments():
    parser = argparse.ArgumentParser(description='CryptoWatcher - 仮想通貨パターン検出システム（チャート付き）')
    
    # 検索条件設定
    parser.add_argument('--days', type=int, default=7,
                       help='検索判定日数 (デフォルト: 7日)')
    parser.add_argument('--range-low', type=float, default=-3.0,
                       help='価格レンジ下限%% (デフォルト: -3.0%%)')
    parser.add_argument('--range-high', type=float, default=3.0,
                       help='価格レンジ上限%% (デフォルト: +3.0%%)')
    
    # フィルタリング条件
    parser.add_argument('--min-volume', type=float, default=100000,
                       help='最小出来高(USDT) (デフォルト: 100000)')
    parser.add_argument('--min-price', type=float, default=0.001,
                       help='最小価格 (デフォルト: 0.001)')
    parser.add_argument('--max-price', type=float, default=1000,
                       help='最大価格 (デフォルト: 1000)')
    
    # 出力オプション
    parser.add_argument('--limit', type=int, default=50,
                       help='分析対象銘柄数 (デフォルト: 50, 0で全銘柄)')
    parser.add_argument('--debug', action='store_true',
                       help='デバッグモードを有効化')
    parser.add_argument('--sort', choices=['volume', 'stability', 'price'], 
                       default='stability', help='ソート基準')
    parser.add_argument('--export-csv', action='store_true',
                       help='CSV形式でエクスポート')
    parser.add_argument('--exclude-stablecoins', action='store_true', default=True,
                       help='ステーブルコインを除外 (デフォルト: 有効)')
    parser.add_argument('--include-stablecoins', action='store_true',
                       help='ステーブルコインも含める')
    parser.add_argument('--all-symbols', action='store_true',
                       help='全銘柄を検索（--limit 0と同じ）')
    parser.add_argument('--chart-rows', type=int, default=5,
                       help='チャートの行数 (デフォルト: 5)')
    parser.add_argument('--chart-cols', type=int, default=4,
                       help='チャートの列数 (デフォルト: 4)')
    
    return parser.parse_args()

def get_binance_symbols(include_stablecoins=False):
    """Binanceから取引可能なUSDTペアを取得（ステーブルコイン制御可能）"""
    print("📡 Binance取引ペア情報を取得中...")
    
    # ステーブルコインリスト
    stablecoins = {
        'USDCUSDT', 'TUSDUSDT', 'BUSDUSDT', 'DAIUSDT', 'USDPUSDT', 
        'FDUSDUSDT', 'PYUSDUSDT', 'EURUSDT', 'GBPUSDT', 'JPYUSDT',
        'AUDUSDT', 'CADUSTD', 'CHFUSDT', 'SEKUSDT', 'NOKUSDT',
        'DKKUSDT', 'PLNUSDT', 'RONUSDT', 'TRYUSDT', 'ZARUSDT',
        'BRLUSDT', 'ARSUSDT', 'UAHUSDT', 'BITKUBUSDT', 'USTCUSDT',
        'USTUSDT', 'USDDUSDT', 'FRAXUSDT', 'LUSDUSDT', 'MIMUSDT',
        'PAXGUSDT', 'XUSDUSDT', 'EURIUSDT'
    }
    
    url = f"{BINANCE_API_URL}/exchangeInfo"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        usdt_symbols = []
        excluded_count = 0
        
        for symbol_info in data['symbols']:
            symbol = symbol_info['symbol']
            if (symbol.endswith('USDT') and 
                symbol_info['status'] == 'TRADING' and
                symbol_info['isSpotTradingAllowed']):
                
                # ステーブルコイン除外設定に応じて処理
                if not include_stablecoins and symbol in stablecoins:
                    excluded_count += 1
                    continue
                    
                usdt_symbols.append(symbol)
        
        print(f"✅ {len(usdt_symbols)}のUSDTペアを取得しました")
        if not include_stablecoins and excluded_count > 0:
            print(f"🚫 {excluded_count}のステーブルコインペアを除外しました")
        return usdt_symbols
        
    except requests.exceptions.RequestException as e:
        print(f"❌ シンボル取得エラー: {e}")
        return []

def get_24hr_ticker():
    """24時間ティッカー情報を取得"""
    print("📊 24時間統計データを取得中...")
    
    url = f"{BINANCE_API_URL}/ticker/24hr"
    
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        ticker_dict = {}
        for ticker in data:
            if ticker['symbol'].endswith('USDT'):
                ticker_dict[ticker['symbol']] = {
                    'price': float(ticker['lastPrice']),
                    'volume': float(ticker['volume']),
                    'quoteVolume': float(ticker['quoteVolume']),
                    'priceChange': float(ticker['priceChange']),
                    'priceChangePercent': float(ticker['priceChangePercent']),
                    'high': float(ticker['highPrice']),
                    'low': float(ticker['lowPrice']),
                    'count': int(ticker['count'])
                }
        
        print(f"✅ {len(ticker_dict)}ペアの統計データを取得しました")
        return ticker_dict
        
    except requests.exceptions.RequestException as e:
        print(f"❌ ティッカー取得エラー: {e}")
        return {}

def get_kline_data(symbol, interval='1d', limit=30):
    """指定シンボルのローソク足データを取得"""
    url = f"{BINANCE_API_URL}/klines"
    params = {'symbol': symbol, 'interval': interval, 'limit': limit}
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        klines = []
        for kline in data:
            klines.append({
                'timestamp': int(kline[0]),
                'date': datetime.fromtimestamp(int(kline[0])/1000),
                'open': float(kline[1]),
                'high': float(kline[2]),
                'low': float(kline[3]),
                'close': float(kline[4]),
                'volume': float(kline[5]),
                'quote_volume': float(kline[7])
            })
        
        return {
            'symbol': symbol,
            'klines': klines,
            'prices': [k['close'] for k in klines],
            'dates': [k['date'] for k in klines],
            'highs': [k['high'] for k in klines],
            'lows': [k['low'] for k in klines],
            'volumes': [k['quote_volume'] for k in klines]
        }
        
    except requests.exceptions.RequestException as e:
        print(f"❌ ローソク足取得エラー ({symbol}): {e}")
        return None

def filter_symbols(symbols, ticker_data, args):
    """基本条件でシンボルをフィルタリング"""
    print("🔍 基本条件でフィルタリング中...")
    
    filtered = []
    stats = {'total': 0, 'volume_fail': 0, 'price_fail': 0}
    
    for symbol in symbols:
        stats['total'] += 1
        if symbol not in ticker_data:
            continue
            
        ticker = ticker_data[symbol]
        
        # フィルタリング条件
        volume_ok = ticker['quoteVolume'] >= args.min_volume
        price_ok = args.min_price <= ticker['price'] <= args.max_price
        
        # 統計
        if not volume_ok: stats['volume_fail'] += 1
        if not price_ok: stats['price_fail'] += 1
        
        if volume_ok and price_ok:
            filtered.append({
                'symbol': symbol,
                'price': ticker['price'],
                'volume': ticker['quoteVolume'],
                'change_24h': ticker['priceChangePercent'],
                'trades': ticker['count']
            })
    
    # 出来高でソート
    filtered.sort(key=lambda x: x['volume'], reverse=True)
    
    # 全銘柄検索の場合は制限しない
    if args.limit == 0 or args.all_symbols:
        print(f"✅ {len(filtered)}ペアが基本条件を満たしました（全銘柄検索）")
        return filtered
    else:
        print(f"✅ {len(filtered)}ペアが基本条件を満たしました")
        return filtered[:args.limit]

def detect_sideways_pattern(kline_data, args):
    """検索パターンを検知"""
    symbol = kline_data['symbol']
    prices = kline_data['prices']
    highs = kline_data['highs']
    lows = kline_data['lows']
    volumes = kline_data['volumes']
    dates = kline_data['dates']
    
    if len(prices) < args.days + 1:
        return None
    
    # 指定日数のデータを取得
    recent_prices = prices[-args.days:]
    recent_highs = highs[-args.days:]
    recent_lows = lows[-args.days:]
    recent_volumes = volumes[-args.days:]
    recent_dates = dates[-args.days:]
    
    # 基準価格（期間開始時の価格）
    base_price = recent_prices[0]
    current_price = recent_prices[-1]
    
    # 価格変動率を計算
    price_changes = []
    for price in recent_prices:
        change_pct = ((price - base_price) / base_price) * 100
        price_changes.append(change_pct)
    
    # 最大・最小変動率
    max_change = max(price_changes)
    min_change = min(price_changes)
    
    # 検索判定
    is_sideways = (min_change >= args.range_low and max_change <= args.range_high)
    
    if not is_sideways:
        return None
    
    # 安定度計算（変動の標準偏差）
    stability = 100 - np.std(price_changes)  # 標準偏差が小さいほど安定
    
    # 高値・安値
    period_high = max(recent_highs)
    period_low = min(recent_lows)
    price_range_pct = ((period_high - period_low) / current_price) * 100
    
    # 出来高の安定性
    volume_stability = 0
    if len(recent_volumes) > 1:
        volume_cv = np.std(recent_volumes) / np.mean(recent_volumes)  # 変動係数
        volume_stability = max(0, 100 - (volume_cv * 100))
    
    # 価格位置（レンジ内での現在位置 0-1）
    if period_high != period_low:
        price_position = (current_price - period_low) / (period_high - period_low)
    else:
        price_position = 0.5
    
    # 総合スコア計算
    stability_score = (stability * 0.4 + 
                      volume_stability * 0.3 + 
                      (100 - price_range_pct) * 0.3)
    
    return {
        'symbol': symbol,
        'base_price': base_price,
        'current_price': current_price,
        'period_high': period_high,
        'period_low': period_low,
        'price_changes': price_changes,
        'max_change': max_change,
        'min_change': min_change,
        'price_range_pct': price_range_pct,
        'stability': stability,
        'volume_stability': volume_stability,
        'price_position': price_position,
        'stability_score': stability_score,
        'days_analyzed': args.days,
        'prices': recent_prices,
        'dates': recent_dates,
        'full_prices': prices,
        'full_dates': dates
    }

def analyze_symbol(symbol_data, args):
    """個別銘柄の検索分析"""
    symbol = symbol_data['symbol']
    
    if args.debug:
        print(f"🔍 {symbol} 分析中...")
    
    # ローソク足データ取得（より多くのデータを取得してチャート表示に備える）
    kline_data = get_kline_data(symbol, interval='1d', limit=max(args.days + 5, 100))
    if not kline_data:
        return None
        
    time.sleep(0.05)  # レート制限対応
    
    # 検索パターン検知
    sideways_result = detect_sideways_pattern(kline_data, args)
    if not sideways_result:
        if args.debug:
            print(f"   ❌ 検索条件不適合")
        return None
    
    if args.debug:
        print(f"   ✅ 検索検知: {sideways_result['min_change']:+.2f}% ~ {sideways_result['max_change']:+.2f}%")
        print(f"   📊 安定度: {sideways_result['stability']:.1f}")
    
    # 基本情報を結果に追加
    sideways_result.update({
        'base_asset': symbol.replace('USDT', ''),
        'volume_usdt': symbol_data['volume'],
        'change_24h': symbol_data['change_24h'],
        'trades_24h': symbol_data['trades']
    })
    
    return sideways_result

def format_number(num):
    """数値を読みやすい形式でフォーマット"""
    if num >= 1_000_000_000:
        return f"${num/1_000_000_000:.1f}B"
    elif num >= 1_000_000:
        return f"${num/1_000_000:.1f}M"
    elif num >= 1_000:
        return f"${num/1_000:.1f}K"
    else:
        return f"${num:.2f}"

def create_chart(signal, ax, args):
    """個別銘柄のチャートを作成"""
    dates = signal['full_dates'][-args.days:]
    prices = signal['full_prices'][-args.days:]
    
    # 価格の変化率を計算
    base_price = prices[0]
    price_change_pct = ((prices[-1] - base_price) / base_price) * 100
    
    # チャート色を決定（上昇: 緑、下降: 赤、検索: 白）
    if price_change_pct > 0.5:
        line_color = '#26a69a'  # 緑
    elif price_change_pct < -0.5:
        line_color = '#ef5350'  # 赤
    else:
        line_color = '#ffffff'  # 白
    
    # ラインチャート描画
    ax.plot(dates, prices, color=line_color, linewidth=1.5)
    
    # グリッドを薄く
    ax.grid(True, alpha=0.2)
    
    # タイトル設定
    title = f"{signal['base_asset']}/USDT"
    ax.set_title(title, fontsize=10, pad=5)
    
    # 価格と変化率を表示
    current_price = prices[-1]
    if current_price < 0.01:
        price_str = f"${current_price:.6f}"
    elif current_price < 1:
        price_str = f"${current_price:.4f}"
    else:
        price_str = f"${current_price:.2f}"
    
    change_str = f"{price_change_pct:+.1f}%"
    
    # 価格情報を右上に表示
    ax.text(0.98, 0.95, price_str, transform=ax.transAxes, 
            fontsize=9, ha='right', va='top', color='white')
    ax.text(0.98, 0.85, change_str, transform=ax.transAxes, 
            fontsize=8, ha='right', va='top', 
            color='#26a69a' if price_change_pct > 0 else '#ef5350')
    
    # x軸の設定
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, args.days // 7)))
    
    # y軸の設定
    ax.tick_params(axis='both', labelsize=8)
    
    # x軸ラベルを回転
    ax.tick_params(axis='x', rotation=45)
    
    # 余白を減らす
    ax.margins(x=0.02, y=0.05)

def display_charts(sideways_signals, args):
    """チャートを表示"""
    if not sideways_signals:
        return
    
    # チャート数を制限
    max_charts = args.chart_rows * args.chart_cols
    signals_to_plot = sideways_signals[:max_charts]
    
    # フィギュアサイズを計算
    fig_width = args.chart_cols * 3
    fig_height = args.chart_rows * 2.5
    
    # フィギュアとサブプロットを作成
    fig = plt.figure(figsize=(fig_width, fig_height), facecolor='#1a1a1a')
    fig.suptitle(f'検索銘柄チャート（{args.days}日間）', fontsize=16, color='white')
    
    # グリッドレイアウト
    gs = GridSpec(args.chart_rows, args.chart_cols, figure=fig, 
                  hspace=0.5, wspace=0.3, 
                  left=0.05, right=0.95, top=0.93, bottom=0.05)
    
    # 各銘柄のチャートを作成
    for i, signal in enumerate(signals_to_plot):
        row = i // args.chart_cols
        col = i % args.chart_cols
        ax = fig.add_subplot(gs[row, col])
        create_chart(signal, ax, args)
    
    # 空のサブプロットを非表示
    total_subplots = args.chart_rows * args.chart_cols
    for i in range(len(signals_to_plot), total_subplots):
        row = i // args.chart_cols
        col = i % args.chart_cols
        ax = fig.add_subplot(gs[row, col])
        ax.set_visible(False)
    
    # チャートを画像として保存
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"sideways_chart_{args.days}days_{timestamp}.png"
    plt.savefig(filename, dpi=150, bbox_inches='tight', facecolor='#1a1a1a')
    print(f"\n💾 チャートを保存しました: {filename}")
    
    # ウィンドウ表示
    plt.show(block=False)
    plt.pause(1)  # チャート表示を確実にする
    input("\n📊 Enterキーを押してチャートを閉じて終了...")
    plt.close('all')

def display_results(sideways_signals, args):
    """結果を表示"""
    print("\n" + "="*80)
    print("📊 検索銘柄検知結果")
    print("="*80)
    print(f"📋 検索条件:")
    print(f"   • 判定日数: {args.days}日")
    print(f"   • 価格レンジ: {args.range_low:+.1f}% ~ {args.range_high:+.1f}%")
    print(f"   • 最小出来高: {format_number(args.min_volume)}")
    print("="*80)
    
    if not sideways_signals:
        print("📝 指定条件の検索銘柄は見つかりませんでした")
        print()
        print("💡 条件緩和の提案:")
        print(f"   python {__file__} --days {max(1, args.days-2)} --range-low {args.range_low-1} --range-high {args.range_high+1}")
        return
    
    # ソート
    if args.sort == 'volume':
        sideways_signals.sort(key=lambda x: x['volume_usdt'], reverse=True)
        sort_desc = "出来高順"
    elif args.sort == 'stability':
        sideways_signals.sort(key=lambda x: x['stability_score'], reverse=True)
        sort_desc = "安定度順"
    elif args.sort == 'price':
        sideways_signals.sort(key=lambda x: x['current_price'], reverse=True)
        sort_desc = "価格順"
    
    print(f"🎯 検知された検索銘柄: {len(sideways_signals)}件 ({sort_desc})\n")
    
    # 最初の10件だけ詳細表示
    for i, signal in enumerate(sideways_signals[:10], 1):
        # 安定度による絵文字
        if signal['stability_score'] >= 80:
            stability_emoji = "🟢"
        elif signal['stability_score'] >= 60:
            stability_emoji = "🟡"
        else:
            stability_emoji = "🟠"
        
        print(f"{i}. {stability_emoji} {signal['symbol']} ({signal['base_asset']}/USDT)")
        print(f"   💰 現在価格: ${signal['current_price']:.6f}")
        print(f"   📊 {args.days}日変動: {signal['min_change']:+.2f}% ~ {signal['max_change']:+.2f}%")
        print(f"   🎯 安定度スコア: {signal['stability_score']:.1f}/100")
        print(f"   💹 出来高: {format_number(signal['volume_usdt'])}")
        print()
    
    if len(sideways_signals) > 10:
        print(f"... 他 {len(sideways_signals) - 10} 件\n")
    
    # チャート表示
    print("📈 チャートを生成中...")
    display_charts(sideways_signals, args)
    print("✅ チャート表示完了")

def save_to_csv(sideways_signals, args):
    """結果をCSVファイルに保存"""
    if not sideways_signals:
        return
    
    csv_data = []
    for signal in sideways_signals:
        csv_data.append({
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'symbol': signal['symbol'],
            'base_asset': signal['base_asset'],
            'current_price': signal['current_price'],
            'days_analyzed': signal['days_analyzed'],
            'min_change_pct': signal['min_change'],
            'max_change_pct': signal['max_change'],
            'stability_score': signal['stability_score'],
            'volume_usdt': signal['volume_usdt'],
            'change_24h': signal['change_24h'],
            'period_high': signal['period_high'],
            'period_low': signal['period_low'],
            'price_range_pct': signal['price_range_pct'],
            'price_position': signal['price_position'],
            'volume_stability': signal['volume_stability']
        })
    
    df = pd.DataFrame(csv_data)
    filename = f"sideways_detection_{args.days}days_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    df.to_csv(filename, index=False)
    print(f"💾 結果をCSVファイルに保存しました: {filename}")

def main():
    args = parse_arguments()
    
    print("🎯 検索銘柄検知システム（チャート付き）")
    print("="*60)
    print(f"📋 検索条件:")
    print(f"   • 判定日数: {args.days}日")
    print(f"   • 価格レンジ: {args.range_low:+.1f}% ~ {args.range_high:+.1f}%")
    print(f"   • 最小出来高: {format_number(args.min_volume)}")
    print(f"   • 価格範囲: ${args.min_price} - ${args.max_price}")
    if args.limit == 0:
        print(f"   • 分析対象: 全銘柄")
    else:
        print(f"   • 分析対象: {args.limit}ペア")
    print(f"   • ソート基準: {args.sort}")
    print(f"   • チャート表示: {args.chart_rows}行 x {args.chart_cols}列")
    print()
    print(f"⏰ 開始時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # ステーブルコイン設定を処理
    include_stablecoins = args.include_stablecoins
    
    # 全銘柄検索の設定
    if args.all_symbols:
        args.limit = 0
    
    # データ取得
    symbols = get_binance_symbols(include_stablecoins)
    if not symbols:
        return
    
    ticker_data = get_24hr_ticker()
    if not ticker_data:
        return
    
    # 基本フィルタリング
    filtered_symbols = filter_symbols(symbols, ticker_data, args)
    if not filtered_symbols:
        return
    
    print(f"\n📊 検索分析開始 (対象: {len(filtered_symbols)}ペア)")
    print("-" * 50)
    
    # 各銘柄を分析
    sideways_signals = []
    for symbol_data in filtered_symbols:
        try:
            result = analyze_symbol(symbol_data, args)
            if result:
                sideways_signals.append(result)
                if not args.debug:
                    print(f"✅ {symbol_data['symbol']}: 検索検知 ({result['min_change']:+.2f}% ~ {result['max_change']:+.2f}%)")
        except Exception as e:
            print(f"⚠️ {symbol_data['symbol']}: エラー - {e}")
            continue
    
    # 結果表示
    display_results(sideways_signals, args)
    
    # CSV保存
    if args.export_csv and sideways_signals:
        save_to_csv(sideways_signals, args)
    
    print("\n" + "="*80)
    print(f"✅ 処理完了 - {datetime.now().strftime('%H:%M:%S')}")
    print(f"🎯 {len(sideways_signals)}件の検索銘柄を検知しました")

if __name__ == "__main__":
    main()