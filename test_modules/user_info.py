def format_user(user: dict) -> str:
    """Format a user dict into a readable string."""
    name = user["name"]
    email = user["email"]
    age = user["age"]
    return f"{name} ({email}), age {age}"