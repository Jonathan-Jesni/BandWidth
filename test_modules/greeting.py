def greet(name: str, role: str) -> str:
    """Return a formatted greeting."""
    template = "Hello, {name}! Your role is {roles}."  # BUG: {roles} instead of {role}
    return template.format(name=name, role=role)
