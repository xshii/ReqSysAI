"""
SSO 跳转认证 Demo
用法: python demo_auth.py
然后访问 http://localhost:5000

需要修改下面的 LOGIN_URL 为你们系统的登录地址
"""
from flask import Flask, redirect, request, session, jsonify
from datetime import timedelta

app = Flask(__name__)
app.secret_key = 'demo-secret-key'
app.permanent_session_lifetime = timedelta(minutes=10)

# ===== 改成你们系统的登录地址 =====
LOGIN_URL = 'http://your-system.com/login'
# 回调地址（本机测试）
CALLBACK_URL = 'http://localhost:5000/callback'


@app.route('/')
def index():
    user = session.get('user')
    if not user:
        # 没登录，跳转到另一个系统
        return redirect(f'{LOGIN_URL}?redirect={CALLBACK_URL}')
    return f'''
    <h2>已登录</h2>
    <p>用户: {user}</p>
    <p>Session 10 分钟有效</p>
    <p><a href="/logout">退出</a></p>
    '''


@app.route('/callback')
def callback():
    """接收另一个系统跳回来的所有参数，先打印看看带了什么"""
    params = dict(request.args)
    headers_of_interest = {
        k: v for k, v in request.headers
        if k.lower() in ('x-forwarded-user', 'x-user', 'authorization', 'cookie')
    }
    return f'''
    <h2>回调收到的数据</h2>
    <h3>URL 参数:</h3>
    <pre>{jsonify(params).get_data(as_text=True)}</pre>
    <h3>相关 Headers:</h3>
    <pre>{jsonify(headers_of_interest).get_data(as_text=True)}</pre>
    <p>把这个页面截图发给我，我就知道怎么对接了</p>
    '''


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


if __name__ == '__main__':
    app.run(debug=True, port=5000)
