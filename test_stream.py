import requests
import json
import argparse
import sys

def test_stream(session_id: str, host: str = "127.0.0.1", port: int = 5000):
    """
    测试 SSE 流式接口，实时打印智能体执行步骤。
    """
    url = f"http://{host}:{port}/api/stream/{session_id}"
    print(f"正在连接到流式接口: {url}")
    print("-" * 50)
    
    try:
        # 必须设置 stream=True 才能接收流式数据
        with requests.get(url, stream=True, timeout=30) as response:
            # 检查 HTTP 状态码
            if response.status_code != 200:
                print(f"请求失败，状态码: {response.status_code}")
                try:
                    print(response.json())
                except json.JSONDecodeError:
                    print(response.text)
                return

            print("连接成功，等待数据流...\n")
            
            # 逐行读取数据
            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    
                    # SSE 格式的数据通常以 "data: " 开头
                    if decoded_line.startswith("data: "):
                        data_str = decoded_line[6:] # 去掉 "data: " 前缀
                        try:
                            # 尝试解析 JSON 数据
                            data = json.loads(data_str)
                            event_type = data.get("type", "unknown")
                            
                            if event_type == "ping":
                                print("🔄 [心跳包] 保持连接活动...")
                            elif event_type == "step":
                                agent = data.get("agent", "Unknown Agent")
                                content = data.get("content", "").strip()
                                print(f"🤖 [{event_type.upper()}] {agent}:\n   {content}\n")
                            elif event_type == "task_completed":
                                desc = data.get('data', {}).get('description', '')
                                print(f"✅ [{event_type.upper()}] 任务完成: {desc}\n")
                            elif event_type == "result":
                                result_data = data.get("data", "")
                                print(f"🎉 [{event_type.upper()}] 最终结果:\n{result_data}\n")
                            elif event_type == "error":
                                msg = data.get("message", "Unknown error")
                                print(f"❌ [{event_type.upper()}] 发生错误: {msg}\n")
                            else:
                                print(f"ℹ️ [{event_type.upper()}] {data}\n")
                                
                        except json.JSONDecodeError:
                            # 如果不是有效的 JSON，直接打印原始字符串
                            print(f"RAW DATA: {data_str}\n")
                    elif decoded_line == ": keep-alive":
                         print("💓 [Keep-Alive] 收到心跳包\n")
                    else:
                        print(f"RAW LINE: {decoded_line}\n")
                        
    except requests.exceptions.RequestException as e:
        print(f"\n❌ 连接发生异常: {e}")
    except KeyboardInterrupt:
        print("\n\n🛑 用户手动中断了测试。")
        sys.exit(0)
        
    print("-" * 50)
    print("流式连接已结束。")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="测试智能体 SSE 流式输出接口")
    parser.add_argument("session_id", help="要测试的 Session ID (必填)")
    parser.add_argument("--host", default="127.0.0.1", help="API 服务器地址 (默认: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="API 服务器端口 (默认: 5000)")
    
    args = parser.parse_args()
    
    test_stream(args.session_id, args.host, args.port)
