"""Lambda handler for Admin panel."""
import json
import logging
import os
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.config import get_config
from common.database import S3SQLiteManager

from .auth import AdminAuthService, get_session_from_cookie
from .routes import AdminRoutes

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global instances
_db: S3SQLiteManager | None = None

# Template directory
TEMPLATE_DIR = Path(__file__).parent / "templates"


def get_db() -> S3SQLiteManager:
    """Get or create database instance."""
    global _db
    if _db is None:
        config = get_config()
        _db = S3SQLiteManager(
            bucket=config.database_bucket,
            key=config.database_key,
        )
    return _db


def load_template(name: str) -> str:
    """Load an HTML template."""
    template_path = TEMPLATE_DIR / name
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    # Fallback to inline templates
    return get_inline_template(name)


def get_inline_template(name: str) -> str:
    """Get inline HTML template as fallback."""
    templates = {
        "login.html": LOGIN_TEMPLATE,
        "dashboard.html": DASHBOARD_TEMPLATE,
    }
    return templates.get(name, "<h1>Template not found</h1>")


# Inline HTML templates (fallback if files not found)
LOGIN_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Login - Telegram Bot</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
               min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .login-box { background: white; padding: 40px; border-radius: 10px;
                     box-shadow: 0 15px 35px rgba(0,0,0,0.2); width: 100%; max-width: 400px; }
        h1 { text-align: center; color: #333; margin-bottom: 30px; }
        .form-group { margin-bottom: 20px; }
        label { display: block; margin-bottom: 5px; color: #666; }
        input[type="password"] { width: 100%; padding: 12px; border: 1px solid #ddd;
                                  border-radius: 5px; font-size: 16px; }
        button { width: 100%; padding: 12px; background: #667eea; color: white;
                 border: none; border-radius: 5px; font-size: 16px; cursor: pointer;
                 transition: background 0.3s; }
        button:hover { background: #5a6fd6; }
        .error { color: #e74c3c; text-align: center; margin-bottom: 20px; }
    </style>
</head>
<body>
    <div class="login-box">
        <h1>🤖 Bot Admin</h1>
        <div id="error" class="error" style="display: none;"></div>
        <form id="loginForm">
            <div class="form-group">
                <label for="password">管理員密碼</label>
                <input type="password" id="password" name="password" required autofocus>
            </div>
            <button type="submit">登入</button>
        </form>
    </div>
    <script>
        // Get base path from current URL (handles API Gateway stage prefix)
        const basePath = window.location.pathname.replace(/\/login$/, '');

        document.getElementById('loginForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const password = document.getElementById('password').value;
            const errorDiv = document.getElementById('error');

            try {
                const response = await fetch(basePath + '/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ password }),
                    credentials: 'include'
                });

                const data = await response.json();

                if (data.success) {
                    window.location.href = basePath;
                } else {
                    errorDiv.textContent = data.error || '登入失敗';
                    errorDiv.style.display = 'block';
                }
            } catch (err) {
                errorDiv.textContent = '登入時發生錯誤';
                errorDiv.style.display = 'block';
            }
        });
    </script>
</body>
</html>"""

DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Dashboard - Telegram Bot</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               background: #f5f6fa; min-height: 100vh; }
        .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                  color: white; padding: 20px; display: flex; justify-content: space-between;
                  align-items: center; }
        .header h1 { font-size: 24px; }
        .logout-btn { background: rgba(255,255,255,0.2); color: white; border: none;
                      padding: 8px 16px; border-radius: 5px; cursor: pointer; }
        .container { max-width: 1200px; margin: 20px auto; padding: 0 20px; }
        .tabs { display: flex; gap: 10px; margin-bottom: 20px; }
        .tab { padding: 10px 20px; background: white; border: none; border-radius: 5px;
               cursor: pointer; font-size: 14px; }
        .tab.active { background: #667eea; color: white; }
        .card { background: white; border-radius: 10px; padding: 20px; margin-bottom: 20px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .card h2 { margin-bottom: 15px; color: #333; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #eee; }
        th { background: #f8f9fa; font-weight: 600; }
        .btn { padding: 6px 12px; border: none; border-radius: 4px; cursor: pointer;
               font-size: 12px; }
        .btn-primary { background: #667eea; color: white; }
        .btn-danger { background: #e74c3c; color: white; }
        .btn-sm { padding: 4px 8px; }
        .form-row { display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; }
        .form-row input { padding: 8px; border: 1px solid #ddd; border-radius: 4px; }
        .form-row input[type="number"] { width: 150px; }
        .form-row input[type="text"] { flex: 1; min-width: 150px; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; }
        .badge-success { background: #2ecc71; color: white; }
        .badge-danger { background: #e74c3c; color: white; }
        .badge-info { background: #3498db; color: white; }
        .badge-warning { background: #f39c12; color: white; }
        .log-entry { padding: 10px; border-bottom: 1px solid #eee; font-size: 13px; }
        .log-entry:last-child { border-bottom: none; }
        .log-time { color: #999; font-size: 11px; }
        .log-message { margin-top: 5px; }
        .hidden { display: none; }
        .status { padding: 4px 8px; border-radius: 4px; font-size: 12px; }
        .status-active { background: #d4edda; color: #155724; }
        .status-inactive { background: #f8d7da; color: #721c24; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 Telegram Bot Admin</h1>
        <button class="logout-btn" onclick="logout()">登出</button>
    </div>

    <div class="container">
        <div class="tabs">
            <button class="tab active" onclick="showTab('users')">用戶管理</button>
            <button class="tab" onclick="showTab('groups')">群組管理</button>
            <button class="tab" onclick="showTab('logs')">系統日誌</button>
        </div>

        <!-- Users Tab -->
        <div id="users-tab" class="card">
            <h2>允許的用戶</h2>
            <div class="form-row">
                <input type="number" id="new-user-id" placeholder="Telegram User ID">
                <input type="text" id="new-username" placeholder="用戶名 (可選)">
                <input type="text" id="new-display-name" placeholder="顯示名稱 (可選)">
                <button class="btn btn-primary" onclick="addUser()">新增用戶</button>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>User ID</th>
                        <th>用戶名</th>
                        <th>顯示名稱</th>
                        <th>新增時間</th>
                        <th>狀態</th>
                        <th>操作</th>
                    </tr>
                </thead>
                <tbody id="users-table"></tbody>
            </table>
        </div>

        <!-- Groups Tab -->
        <div id="groups-tab" class="card hidden">
            <h2>允許的群組</h2>
            <div class="form-row">
                <input type="number" id="new-group-id" placeholder="Telegram Group ID (負數)">
                <input type="text" id="new-group-name" placeholder="群組名稱 (可選)">
                <button class="btn btn-primary" onclick="addGroup()">新增群組</button>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Group ID</th>
                        <th>群組名稱</th>
                        <th>新增時間</th>
                        <th>狀態</th>
                        <th>操作</th>
                    </tr>
                </thead>
                <tbody id="groups-table"></tbody>
            </table>
        </div>

        <!-- Logs Tab -->
        <div id="logs-tab" class="card hidden">
            <h2>系統日誌</h2>
            <div class="form-row">
                <select id="log-level" onchange="loadLogs()">
                    <option value="">全部等級</option>
                    <option value="ERROR">ERROR</option>
                    <option value="WARNING">WARNING</option>
                    <option value="INFO">INFO</option>
                    <option value="DEBUG">DEBUG</option>
                </select>
                <button class="btn btn-primary" onclick="loadLogs()">重新整理</button>
            </div>
            <div id="logs-container"></div>
        </div>
    </div>

    <script>
        // Get base path from current URL (handles API Gateway stage prefix)
        const basePath = window.location.pathname.replace(/\/$/, '');
        let currentTab = 'users';

        function showTab(tab) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.card').forEach(c => c.classList.add('hidden'));

            event.target.classList.add('active');
            document.getElementById(tab + '-tab').classList.remove('hidden');
            currentTab = tab;

            if (tab === 'users') loadUsers();
            else if (tab === 'groups') loadGroups();
            else if (tab === 'logs') loadLogs();
        }

        async function apiCall(url, options = {}) {
            const response = await fetch(basePath + url, {
                ...options,
                headers: { 'Content-Type': 'application/json', ...options.headers },
                credentials: 'include'
            });
            if (response.status === 401) {
                window.location.href = basePath + '/login';
                return null;
            }
            return response.json();
        }

        async function loadUsers() {
            const data = await apiCall('/users');
            if (!data) return;

            const tbody = document.getElementById('users-table');
            tbody.innerHTML = data.users.map(u => `
                <tr>
                    <td>${u.telegram_user_id}</td>
                    <td>${u.username || '-'}</td>
                    <td>${u.display_name || '-'}</td>
                    <td>${new Date(u.added_at).toLocaleString('zh-TW')}</td>
                    <td><span class="status ${u.is_active ? 'status-active' : 'status-inactive'}">
                        ${u.is_active ? '啟用' : '停用'}</span></td>
                    <td><button class="btn btn-danger btn-sm" onclick="removeUser(${u.telegram_user_id})">刪除</button></td>
                </tr>
            `).join('');
        }

        async function addUser() {
            const userId = document.getElementById('new-user-id').value;
            const username = document.getElementById('new-username').value;
            const displayName = document.getElementById('new-display-name').value;

            if (!userId) { alert('請輸入 User ID'); return; }

            await apiCall('/users', {
                method: 'POST',
                body: JSON.stringify({
                    telegram_user_id: userId,
                    username: username || undefined,
                    display_name: displayName || undefined
                })
            });

            document.getElementById('new-user-id').value = '';
            document.getElementById('new-username').value = '';
            document.getElementById('new-display-name').value = '';
            loadUsers();
        }

        async function removeUser(userId) {
            if (!confirm('確定要刪除此用戶？')) return;
            await apiCall('/users/' + userId, { method: 'DELETE' });
            loadUsers();
        }

        async function loadGroups() {
            const data = await apiCall('/groups');
            if (!data) return;

            const tbody = document.getElementById('groups-table');
            tbody.innerHTML = data.groups.map(g => `
                <tr>
                    <td>${g.telegram_group_id}</td>
                    <td>${g.group_name || '-'}</td>
                    <td>${new Date(g.added_at).toLocaleString('zh-TW')}</td>
                    <td><span class="status ${g.is_active ? 'status-active' : 'status-inactive'}">
                        ${g.is_active ? '啟用' : '停用'}</span></td>
                    <td><button class="btn btn-danger btn-sm" onclick="removeGroup(${g.telegram_group_id})">刪除</button></td>
                </tr>
            `).join('');
        }

        async function addGroup() {
            const groupId = document.getElementById('new-group-id').value;
            const groupName = document.getElementById('new-group-name').value;

            if (!groupId) { alert('請輸入 Group ID'); return; }

            await apiCall('/groups', {
                method: 'POST',
                body: JSON.stringify({
                    telegram_group_id: groupId,
                    group_name: groupName || undefined
                })
            });

            document.getElementById('new-group-id').value = '';
            document.getElementById('new-group-name').value = '';
            loadGroups();
        }

        async function removeGroup(groupId) {
            if (!confirm('確定要刪除此群組？')) return;
            await apiCall('/groups/' + groupId, { method: 'DELETE' });
            loadGroups();
        }

        async function loadLogs() {
            const level = document.getElementById('log-level').value;
            const url = '/logs' + (level ? '?level=' + level : '');
            const data = await apiCall(url);
            if (!data) return;

            const container = document.getElementById('logs-container');
            container.innerHTML = data.logs.map(log => `
                <div class="log-entry">
                    <span class="badge badge-${log.level === 'ERROR' ? 'danger' :
                        log.level === 'WARNING' ? 'warning' :
                        log.level === 'INFO' ? 'info' : 'success'}">${log.level}</span>
                    <span class="log-time">${new Date(log.created_at).toLocaleString('zh-TW')}</span>
                    <span>[${log.source}]</span>
                    ${log.telegram_user_id ? '<span>User: ' + log.telegram_user_id + '</span>' : ''}
                    <div class="log-message">${log.message}</div>
                </div>
            `).join('') || '<p>沒有日誌記錄</p>';
        }

        async function logout() {
            await apiCall('/logout', { method: 'POST' });
            window.location.href = basePath + '/login';
        }

        // Initial load
        loadUsers();
    </script>
</body>
</html>"""


def create_response(
    status_code: int,
    body: str | dict,
    content_type: str = "application/json",
    cookies: list[str] | None = None,
) -> dict:
    """Create API Gateway response."""
    headers = {
        "Content-Type": content_type,
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Credentials": "true",
    }

    if cookies:
        headers["Set-Cookie"] = "; ".join(cookies)

    if isinstance(body, dict):
        body = json.dumps(body)

    return {
        "statusCode": status_code,
        "headers": headers,
        "body": body,
    }


def lambda_handler(event: dict, context) -> dict:
    """
    Lambda handler for Admin panel.

    Args:
        event: API Gateway event
        context: Lambda context

    Returns:
        API Gateway response
    """
    logger.info(f"Admin request: {event.get('httpMethod')} {event.get('path')}")

    try:
        config = get_config()
    except Exception as e:
        logger.error(f"Configuration error: {e}")
        return create_response(500, {"error": "Configuration error"})

    db = get_db()
    auth_service = AdminAuthService(db, config.admin_password)
    routes = AdminRoutes(db)

    # Get request details
    method = event.get("httpMethod", "GET")
    path = event.get("path", "/admin")
    headers = event.get("headers", {})
    query_params = event.get("queryStringParameters") or {}
    path_params = event.get("pathParameters") or {}

    # Get stage from request context for correct cookie path
    stage = event.get("requestContext", {}).get("stage", "prod")
    cookie_path = f"/{stage}/admin"

    # Parse body
    body = {}
    if event.get("body"):
        try:
            body = json.loads(event["body"])
        except json.JSONDecodeError:
            pass

    # Get session from cookie
    cookie_header = headers.get("cookie") or headers.get("Cookie")
    session_token = get_session_from_cookie(cookie_header)

    # Get client IP
    client_ip = headers.get("x-forwarded-for", "").split(",")[0].strip()

    # Route handling
    # Login page
    if path == "/admin/login":
        if method == "GET":
            return create_response(200, load_template("login.html"), "text/html")
        elif method == "POST":
            password = body.get("password", "")
            token = auth_service.login(password, client_ip)
            if token:
                cookie = f"session={token}; HttpOnly; Secure; SameSite=Strict; Path={cookie_path}; Max-Age={24*60*60}"
                return create_response(
                    200,
                    {"success": True},
                    cookies=[cookie],
                )
            else:
                return create_response(401, {"error": "密碼錯誤或登入次數過多"})

    # Logout
    if path == "/admin/logout" and method == "POST":
        if session_token:
            auth_service.logout(session_token)
        cookie = f"session=; HttpOnly; Secure; SameSite=Strict; Path={cookie_path}; Max-Age=0"
        return create_response(200, {"success": True}, cookies=[cookie])

    # All other routes require authentication
    if not auth_service.validate_session(session_token):
        if method == "GET" and path == "/admin":
            # Redirect to login page
            return {
                "statusCode": 302,
                "headers": {"Location": f"/{stage}/admin/login"},
                "body": "",
            }
        return create_response(401, {"error": "Unauthorized"})

    # Dashboard
    if path == "/admin" and method == "GET":
        return create_response(200, load_template("dashboard.html"), "text/html")

    # Users API
    if path == "/admin/users":
        if method == "GET":
            return routes.list_users()
        elif method == "POST":
            return routes.add_user(body)

    if path.startswith("/admin/users/") and method == "DELETE":
        user_id = path.split("/")[-1]
        return routes.remove_user(user_id)

    # Groups API
    if path == "/admin/groups":
        if method == "GET":
            return routes.list_groups()
        elif method == "POST":
            return routes.add_group(body)

    if path.startswith("/admin/groups/") and method == "DELETE":
        group_id = path.split("/")[-1]
        return routes.remove_group(group_id)

    # Logs API
    if path == "/admin/logs" and method == "GET":
        level = query_params.get("level")
        limit = int(query_params.get("limit", 100))
        offset = int(query_params.get("offset", 0))
        return routes.get_logs(level, limit, offset)

    # Not found
    return create_response(404, {"error": "Not found"})
