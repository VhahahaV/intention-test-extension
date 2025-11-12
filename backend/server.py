"""向后兼容的启动脚本，实际逻辑位于 app.server。"""

try:
    from app.server import main, start_http_server  # running from project root
except ImportError:
    from app import server as _app_server  # running inside backend directory

    main = _app_server.main
    start_http_server = _app_server.start_http_server

__all__ = ["start_http_server", "main"]


if __name__ == "__main__":
    main()
