#!/bin/bash
echo "=== 后端连接调试工具 ==="
echo ""

echo "1. 检查容器状态:"
docker ps | grep intention-test || echo "❌ 容器未运行"
echo ""

echo "2. 检查后端进程:"
docker exec intention-test-dev ps aux | grep server.py || echo "❌ 后端进程未运行"
echo ""

echo "3. 检查端口监听:"
docker exec intention-test-dev netstat -tuln | grep 8080 || echo "❌ 端口未监听"
echo ""

echo "4. 检查后端日志（最后10行）:"
docker logs --tail 10 intention-test-dev
echo ""

echo "5. 测试 /session 端点:"
curl -s -X POST http://localhost:8080/session \
  -H "Content-Type: application/json" \
  -d '{"type":"query","data":{}}' \
  -w "\nHTTP Status: %{http_code}\n" | head -5
echo ""

echo "6. 检查扩展端口配置:"
echo "请在 Cursor 中检查：设置 → 搜索 'intentionTest.port' 或 'intention-test.port'"
echo "应该设置为: 8080"
echo ""

echo "7. 检查端口占用（宿主机）:"
lsof -i :8080 | head -5 || echo "端口未被占用"
echo ""

echo "=== 调试完成 ==="
