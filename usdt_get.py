import ccxt
import json
import requests
from config_utils import load_config

# 禁用SSL警告（代理环境下避免证书报错）
requests.packages.urllib3.disable_warnings()

# ========== 核心配置 ==========
config = load_config()
PROXY_URL = config["proxy"]["http"]

# OKX模拟盘API配置
API_CONFIG = {
    "apiKey": config["okx"]["api_key"],
    "secret": config["okx"]["api_secret"],
    "password": config["okx"]["api_passphrase"],
    "enableRateLimit": True,
    "options": {
        "defaultType": "spot",  # 现货模式
        "fetchBalance": "all"
    },
    "proxies": {
        "http": PROXY_URL,
        "https": PROXY_URL
    }
}

def create_proxy_session():
    session = requests.Session()
    session.proxies = {
        "http": PROXY_URL,
        "https": PROXY_URL,
    }
    session.timeout = 15
    return session

def test_proxy_connectivity():
    try:
        session = create_proxy_session()
        response = session.get("https://www.okx.com")
        if response.status_code == 200:
            print("✅ 代理连通性测试成功")
            return True
        else:
            print(f"❌ 代理测试失败，状态码: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 代理连接失败: {str(e)}")
        return False

def get_okx_sandbox_balance():
    """获取现货杠杆账户余额"""
    try:
        okx = ccxt.okx({
            **API_CONFIG,
            'sandbox': True,
            'hostname': 'www.okx.com',
        })
        okx.load_markets()

        # 获取现货杠杆账户余额（margin账户）
        print("🔄 正在获取OKX现货杠杆模拟盘账户资产...")
        balance = okx.fetch_balance({"type": "margin"})  # 指定margin账户

        print("\n=== OKX现货杠杆模拟盘账户资产汇总 ===")
        total_usdt = balance.get('total', {}).get('USDT', 0)
        print(f"总资产(USDT): {total_usdt}")

        non_zero_assets = {}
        for coin, amount in balance['total'].items():
            if float(amount) > 0.000001:
                non_zero_assets[coin] = {
                    '总计': round(float(amount), 6),
                    '可用': round(float(balance['free'].get(coin, 0)), 6),
                    '已用': round(float(balance['used'].get(coin, 0)), 6)
                }

        if non_zero_assets:
            print("\n=== 非零资产明细 ===")
            for coin, info in non_zero_assets.items():
                print(f"{coin}: {info}")
        else:
            print("\n⚠️  现货杠杆账户暂无可用资产")

        return balance

    except ccxt.AuthenticationError as e:
        print(f"\n❌ 认证失败: {str(e)}")
        print("排查方向：1. API密钥正确性 2. 模拟盘API 3. IP白名单")
        return None
    except ccxt.NetworkError as e:
        print(f"\n❌ 网络错误: {str(e)}")
        print("排查方向：1. 代理配置 2. 代理软件运行状态")
        return None
    except Exception as e:
        print(f"\n❌ 获取资产失败: {str(e)}")
        return None

if __name__ == "__main__":
    if test_proxy_connectivity():
        get_okx_sandbox_balance()