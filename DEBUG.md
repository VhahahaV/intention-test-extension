# 调试指南：扩展无法连接到后端

## 问题症状
- 扩展弹出窗口中 System 信息不显示
- 没有错误信息
- 怀疑是端口连接问题

## 调试步骤

### 1. 检查后端是否运行

```bash
# 检查容器状态
docker ps | grep intention-test

# 检查后端进程
docker exec intention-test-dev ps aux | grep server.py

# 检查端口监听
docker exec intention-test-dev netstat -tuln | grep 8080
# 或
docker exec intention-test-dev ss -tuln | grep 8080
```

### 2. 检查后端日志

```bash
# 查看最新日志
docker logs --tail 50 intention-test-dev

# 实时查看日志
docker logs -f intention-test-dev
```

### 3. 测试后端 API

```bash
# 测试 /session 端点（扩展使用的端点）
curl -v -X POST http://localhost:8080/session \
  -H "Content-Type: application/json" \
  -d '{"type":"query","data":{"target_focal_method":"test","target_focal_file":"test.java","test_desc":"test","project_path":"/test","focal_file_path":"/test/test.java"}}'

# 测试 /junitVersion 端点
curl -v -X POST http://localhost:8080/junitVersion \
  -H "Content-Type: application/json" \
  -d '{"data":4}'
```

**预期结果**：
- `/session` 应该返回 200 并开始流式响应
- `/junitVersion` 应该返回 200

**如果返回 404**：
- 检查是否有其他服务占用 8080 端口
- 检查后端路由是否正确

### 4. 检查扩展端口配置

在 Cursor/VS Code 中：
1. 打开设置（Cmd+, 或 Ctrl+,）
2. 搜索 `intentionTest.port` 或 `intention-test.port`
3. 确认端口设置为 `8080`

或检查 `.vscode/settings.json`：
```json
{
  "intentionTest.port": 8080
}
```

### 5. 检查网络连接

```bash
# 从宿主机测试容器端口
curl -v http://localhost:8080/session

# 从容器内测试
docker exec intention-test-dev curl -v http://localhost:8080/session
```

### 6. 检查后端配置

```bash
# 进入容器检查配置
docker exec -it intention-test-dev /bin/bash
cat /app/backend/config.ini

# 检查环境变量
echo $JAVA_HOME
echo $OPENAI_API_KEY
```

### 7. 重启后端

```bash
# 重启容器
docker restart intention-test-dev

# 或停止并重新启动
docker stop intention-test-dev
docker rm intention-test-dev
docker run -d --name intention-test-dev \
  -p 8080:8080 \
  -v /Users/vhahahav/Code/intention-test-extension:/app \
  vhahahav/intention_test:latest
```

### 8. 检查扩展连接

在扩展的开发者工具中：
1. 打开扩展开发窗口（Extension Development Host）
2. Help → Toggle Developer Tools
3. 查看 Console 标签页的错误信息
4. 查看 Network 标签页的请求

### 9. 常见问题

#### 问题 1: 端口被占用
```bash
# 检查端口占用
lsof -i :8080
# 或
netstat -an | grep 8080

# 杀死占用进程
kill -9 <PID>
```

#### 问题 2: 容器内端口未正确映射
```bash
# 检查端口映射
docker port intention-test-dev

# 应该显示：8080/tcp -> 0.0.0.0:8080
```

#### 问题 3: 防火墙阻止连接
- macOS: 检查系统偏好设置 → 安全性与隐私 → 防火墙
- Linux: 检查 iptables 或 ufw

#### 问题 4: 扩展配置错误
- 确认扩展配置中的端口号与后端一致
- 确认扩展连接到 `localhost` 而不是其他地址

### 10. 详细日志模式

如果需要更详细的日志：

```bash
# 进入容器
docker exec -it intention-test-dev /bin/bash

# 停止当前后端
pkill -f server.py

# 手动启动后端（带详细日志）
cd /app/backend
python server.py --port 8080
```

### 11. 验证完整流程

1. 后端启动成功 → 日志显示 "HTTP server is started and listening on 8080"
2. 端口监听正常 → `netstat` 显示 8080 端口在 LISTEN
3. API 响应正常 → `curl` 测试返回 200
4. 扩展配置正确 → 设置中端口为 8080
5. 扩展连接成功 → 开发者工具中看到请求成功

## 当前发现的问题

### 问题 1: 从宿主机访问返回 404
- **症状**: `curl http://localhost:8080/session` 返回 404，响应头显示 `server: uvicorn`
- **原因**: Cursor 也在监听 8080 端口，可能拦截了请求
- **解决**: 
  1. 检查扩展端口配置是否正确
  2. 确认扩展连接到 `localhost:8080`
  3. 如果 Cursor 占用端口，考虑使用其他端口（如 8081）

### 问题 2: 从容器内访问返回 400
- **症状**: 从容器内测试返回 400 Bad Request，错误信息：`KeyError: 'target_focal_method'`
- **原因**: 请求数据格式不完整，缺少必需字段
- **说明**: 这是正常的，因为测试请求不包含完整的扩展请求数据

### 问题 3: System 信息不显示
- **可能原因**:
  1. 扩展未正确连接到后端（端口配置错误）
  2. 扩展未发送请求（UI 未触发）
  3. 后端未正确响应（需要检查日志）

## 如果问题仍然存在

1. 收集以下信息：
   - 后端日志：`docker logs intention-test-dev > backend.log`
   - 扩展开发者工具 Console 输出
   - 扩展开发者工具 Network 请求详情
   - 系统端口占用情况：`lsof -i :8080`

2. 检查是否有多个后端实例在运行：
   ```bash
   ps aux | grep server.py
   docker ps -a | grep intention-test
   ```

3. 尝试使用不同的端口：
   - 修改后端端口：`docker run -p 8081:8081 -e SERVER_PORT=8081 ...`
   - 修改扩展配置：`"intentionTest.port": 8081`

