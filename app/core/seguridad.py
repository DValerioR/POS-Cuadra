import bcrypt

# bcrypt solo usa los primeros 72 bytes de la contraseña; la versión 5 marca
# error si son más, así que se valida antes.
MAX_BYTES_PASSWORD = 72


def hashear_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verificar_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
