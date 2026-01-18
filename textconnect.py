import requests

# 你的V2RayN本地代理配置（端口10808，SOCKS5协议）
PROXY = {
    'http': 'socks5://127.0.0.1:10808',
    'https': 'socks5://127.0.0.1:10808'
}


# 测试访问谷歌（强制用V2RayN代理）
def test_google():
    try:
        print("测试Python访问谷歌...")
        # 强制使用代理，同时关闭SSL证书验证（避免环境差异）
        response = requests.get(
            'https://www.google.com',
            proxies=PROXY,
            timeout=15,
            verify=False
        )
        print(f"✅ Python访问谷歌成功！状态码: {response.status_code}")
        print(f"页面标题: {response.text.split('<title>')[1].split('</title>')[0]}")
    except requests.exceptions.ProxyError:
        print("❌ 代理连接失败：请确认V2RayN已运行，且端口是10808")
    except Exception as e:
        print(f"❌ 错误：{str(e)[:100]}")


# 测试访问OKX（和你的量化策略需求一致）
def test_okx():
    try:
        print("\n测试Python访问OKX...")
        response = requests.get(
            'https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT-SWAP',
            proxies=PROXY,
            timeout=15,
            verify=False
        )
        print(f"✅ Python访问OKX成功！状态码: {response.status_code}")
        print(f"OKX返回数据: {response.json()['data'][0]['last']}")
    except Exception as e:
        print(f"❌ 错误：{str(e)[:100]}")


if __name__ == "__main__":
    # 先安装依赖（如果没装过）
    try:
        import requests
    except ImportError:
        print("正在安装requests库...")
        import subprocess

        subprocess.run(["pip", "install", "requests"], check=True)

    # 执行测试
    test_google()
    test_okx()