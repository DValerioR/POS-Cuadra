"""Certificado HTTPS para la red local, para que la tableta pueda usar la cámara.

Chrome solo deja usar la cámara en una conexión segura (HTTPS). En la red de
la farmacia no hay un certificado "de internet", así que se crea uno propio:

1. Una autoridad local ("Cuadra - red local"), válida 10 años. Su archivo
   `ca.crt` se puede instalar en la tableta (Ajustes → Seguridad → Instalar
   certificado → Certificado de CA) para que Chrome no muestre el aviso; si
   no se instala, basta con aceptar el aviso una vez ("Avanzado → Continuar").
2. El certificado del servidor, firmado por esa autoridad, para el nombre de
   esta computadora y sus direcciones de red (y las que se pasen con --ip).

Uso (en la computadora que hace de servidor):
    python -m app.scripts.certificado_local
    python -m app.scripts.certificado_local --ip 192.168.1.50

Quedan en ./certificados/ (no se sube a GitHub). Si ya existe la autoridad
se reutiliza, así la tableta no tiene que volver a instalarla cuando cambia
la IP del servidor. Después el servidor HTTPS se arranca con servidor_https.cmd.
"""

import argparse
import ipaddress
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CARPETA = Path("certificados")


def ip_de_salida() -> str | None:
    """La IP con la que esta computadora sale a la red (la que usará la
    tableta); no la de adaptadores virtuales como WSL o Hyper-V."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def direcciones_locales() -> set[str]:
    """IPv4 de esta computadora en la red (sin la de loopback)."""
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except socket.gaierror:
        pass
    if salida := ip_de_salida():
        ips.add(salida)  # aunque el nombre de la computadora no resuelva
    return {ip for ip in ips if not ip.startswith("127.")}


def _guardar_llave(llave, ruta: Path) -> None:
    ruta.write_bytes(llave.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))


def autoridad() -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    crt, key = CARPETA / "ca.crt", CARPETA / "ca.key"
    if crt.exists() and key.exists():
        return (x509.load_pem_x509_certificate(crt.read_bytes()),
                serialization.load_pem_private_key(key.read_bytes(), password=None))
    llave = ec.generate_private_key(ec.SECP256R1())
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Cuadra - red local"),
                        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Cuadra")])
    ahora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nombre).issuer_name(nombre).public_key(llave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - timedelta(days=1)).not_valid_after(ahora + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                                     key_encipherment=False, data_encipherment=False, key_agreement=False,
                                     encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(llave.public_key()), critical=False)
        .sign(llave, hashes.SHA256())
    )
    _guardar_llave(llave, key)
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert, llave


def servidor(ca: x509.Certificate, ca_llave, nombres: list[str], ips: list[str]) -> x509.Certificate:
    llave = ec.generate_private_key(ec.SECP256R1())
    ahora = datetime.now(timezone.utc)
    alternativos = [x509.DNSName(n) for n in nombres] + [x509.IPAddress(ipaddress.ip_address(ip)) for ip in ips]
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, nombres[0])]))
        .issuer_name(ca.subject).public_key(llave.public_key())
        .serial_number(x509.random_serial_number())
        # Menos de 398 días: Chrome no acepta certificados más largos.
        .not_valid_before(ahora - timedelta(days=1)).not_valid_after(ahora + timedelta(days=390))
        .add_extension(x509.SubjectAlternativeName(alternativos), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_llave.public_key()), critical=False)
        .sign(ca_llave, hashes.SHA256())
    )
    _guardar_llave(llave, CARPETA / "servidor.key")
    (CARPETA / "servidor.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert


def main() -> None:
    parser = argparse.ArgumentParser(description="Certificado HTTPS para la red local (cámara de la tableta)")
    parser.add_argument("--ip", action="append", default=[], help="otra IP del servidor (se puede repetir)")
    args = parser.parse_args()
    for ip in args.ip:
        ipaddress.ip_address(ip)  # falla si no es una IP
    CARPETA.mkdir(exist_ok=True)
    ca, ca_llave = autoridad()
    nombre = socket.gethostname()
    nombres = [nombre, "localhost"] + ([f"{nombre}.local"] if "." not in nombre else [])
    ips = sorted(direcciones_locales() | set(args.ip)) + ["127.0.0.1"]
    cert = servidor(ca, ca_llave, nombres, ips)
    print(f"Certificado listo en {CARPETA.resolve()} (vence el {cert.not_valid_after_utc:%d/%m/%Y}).")
    print("Nombres: " + ", ".join(nombres))
    print("Direcciones: " + ", ".join(ips))
    principal = (args.ip or [None])[0] or ip_de_salida()
    if principal:
        print(f"En la tableta abre: https://{principal}:8443/tableta")
    print("Para no ver el aviso de seguridad, instala en la tableta el certificado que se descarga en /certificado.")


if __name__ == "__main__":
    main()
