"""Certificado HTTPS de la red local (para la cámara de la tableta)."""

from cryptography import x509

from app.scripts import certificado_local


def test_genera_autoridad_y_certificado(tmp_path, monkeypatch):
    monkeypatch.setattr(certificado_local, "CARPETA", tmp_path)
    ca, llave = certificado_local.autoridad()
    cert = certificado_local.servidor(ca, llave, ["farmacia", "localhost"], ["192.168.1.50", "127.0.0.1"])
    alternativos = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert alternativos.get_values_for_type(x509.DNSName) == ["farmacia", "localhost"]
    assert [str(ip) for ip in alternativos.get_values_for_type(x509.IPAddress)] == ["192.168.1.50", "127.0.0.1"]
    assert cert.issuer == ca.subject
    assert (cert.not_valid_after_utc - cert.not_valid_before_utc).days < 398  # límite de Chrome
    # La autoridad se reutiliza: la tableta no tiene que instalarla otra vez.
    otra, _ = certificado_local.autoridad()
    assert otra.serial_number == ca.serial_number
    assert {p.name for p in tmp_path.iterdir()} == {"ca.crt", "ca.key", "servidor.crt", "servidor.key"}
