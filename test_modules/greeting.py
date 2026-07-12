def greet(name: str, role: str) -> str:
    """Return a formatted greeting."""
    template = "Hello, {name}! Your role is {role}."
    return template.format(name=name, role=role)