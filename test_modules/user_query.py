def build_user_query(username: str) -> str:
    """Build a SQL query to find a user by name."""
    return f"SELECT * FROM users WHERE name = '{username}'"  # BUG: SQL injection -- should use parameterized queries
