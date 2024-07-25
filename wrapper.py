from functools import wraps
from flask import render_template_string, session


def role_required(roles):
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'id_token' not in session or 'role' not in session:
                return render_template_string('''
                    <script>
                        alert("You need to log in first.");
                        window.location.href = "{{ url_for('auth.login') }}";
                    </script>
                ''')
            if session['role'] not in roles:
                return render_template_string('''
                    <script>
                        alert("You do not have permission to access this page.");
                        window.location.href = "{{ url_for('main.index') }}";
                    </script>
                ''')
            return f(*args, **kwargs)
        return decorated_function
    return wrapper


# Define login_required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'id_token' not in session:
            return render_template_string('''
                <script>
                    alert("You need to log in first.");
                    window.location.href = "{{ url_for('auth.login') }}";
                </script>
            ''')
        return f(*args, **kwargs)
    return decorated_function