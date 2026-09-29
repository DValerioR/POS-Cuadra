from alembic import command


def test_migraciones_coinciden_con_modelos(alembic_config):
    """Si alguien cambia un modelo y olvida generar la migración, esto falla."""
    command.check(alembic_config)
