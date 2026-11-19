# Activación Webpay en la EC2 de Pago

Ejecutar desde AWS CloudShell o un equipo con AWS CLI v2, Python 3.8 o posterior
y acceso al repositorio. El comando utiliza SSM para operar sobre la EC2
`i-0241836a7e45a2e3f` en `us-east-1`, con el contenedor `ev3-pago` y la
imagen [verificada en GHCR](https://github.com/ZorVaK749/fazbear-pago/actions/runs/44433036627)
fijada en `sha256:2e93d9d7b905480c1704bbc31644ba3e2e67410fd1fe0da6ca8c54ac49c61c12`.
La EC2 debe ser un nodo Linux administrado por SSM y tener Bash, Python, Docker,
`base64` y `gzip`. La modalidad SecureString también requiere AWS CLI en la EC2.

## Uso

```bash
git clone -b ev3/webpay-integracion https://github.com/ZorVaK749/fazbear-pago.git
cd fazbear-pago
python3 deploy/aws/webpay.py --dry-run
python3 deploy/aws/webpay.py --apply
python3 deploy/aws/webpay.py --status
```

En un clon existente de la rama, actualizar con `git pull --ff-only`.
`--dry-run` y `--status` consultan AWS y emiten una invocación SSM de inspección.
El dry run verifica el entorno y los permisos del archivo sin leer valores de
SecureString. Si hay más de un Target Group que coincide, añadir
`--target-group-arn "$PAGO_TARGET_GROUP_ARN"` a cada comando. Para el corte se
exige que el registro de Pago en 8087 sea el único destino del grupo y que
comience en estado `healthy`.

Durante el corte hay una interrupción breve. El script valida que el contenedor
actual use la imagen fijada, el puerto 8087:8080, UID:GID 10001:10001, 640 MiB y
`unless-stopped`. Crea un candidato con la configuración Docker y el entorno
activos, modifica las cuatro variables Webpay, respalda el archivo, conserva
el contenedor anterior detenido y sustituye `pago.env` de forma atómica.
Usa la imagen local en EC2 por digest. Al finalizar exige HTTP 200 con modalidad
`SIMULATION_AND_WEBPAY_INTEGRATION` y salud del Target Group en observaciones
separadas por al menos un intervalo de health check.

El respaldo y el diario quedan en `/etc/pedidos360/ev3/.webpay-rollout/`, con
permisos de root. El contenedor anterior queda como
`ev3-pago-previous-<id>`. Conservar ambos durante la validación.
Confirmar en el frontend una transacción con Entra y tarjetas de integración.
El script usa el retorno fijo
`https://p5gsy16utd.execute-api.us-east-1.amazonaws.com/checkout/webpay`.
Las rutas JWT existentes se mantienen.

## Credenciales e IAM

**Opción principal, Parameter Store.** El responsable del laboratorio carga
dos parámetros `SecureString` en `us-east-1`, con los valores de integración
de la [referencia oficial de Transbank](https://github.com/TransbankDevelopers/transbank-developers-docs/blob/master/referencia/webpay/README.md).

| Parámetro | Variable |
| --- | --- |
| `/pedidos360/ev3/webpay/commerce-code` | `WEBPAY_COMMERCE_CODE` |
| `/pedidos360/ev3/webpay/api-key` | `WEBPAY_API_KEY` |

El operador de CloudShell necesita:

- `ec2:DescribeInstances`, `elasticloadbalancing:DescribeTargetGroups` y
  `elasticloadbalancing:DescribeTargetHealth` para localizar y validar el destino.
- `ssm:SendCommand` limitado a
  `arn:aws:ec2:us-east-1:ACCOUNT_ID:instance/i-0241836a7e45a2e3f` y al documento
  `arn:aws:ssm:us-east-1::document/AWS-RunShellScript`. El documento permite
  ejecutar comandos como root en el nodo autorizado.
- `ssm:ListCommandInvocations` y `ssm:GetCommandInvocation` para consultar la ejecución.

El rol de la **EC2** conserva el acceso de nodo administrado de SSM y agrega
`ssm:GetParameters` limitado a estos recursos:

```text
arn:aws:ssm:us-east-1:ACCOUNT_ID:parameter/pedidos360/ev3/webpay/commerce-code
arn:aws:ssm:us-east-1:ACCOUNT_ID:parameter/pedidos360/ev3/webpay/api-key
```

Para una clave KMS administrada por el equipo, añadir `kms:Decrypt` sobre su
ARN y permitir al rol en la política de la clave. Usar condiciones de servicio
y contexto de cifrado para los dos parámetros si el laboratorio las admite.
La cuenta operadora necesita permisos de escritura de parámetros solo si
también le corresponde provisionarlos. El despliegue prefiere SecureString
frente a Secrets Manager por su alcance de dos parámetros y el uso de SSM
existente. El código y el key viajan desde Parameter Store a la EC2 y se
escriben localmente como configuración de root. Run Command recibe el
código del script y sus opciones.

**Alternativa si el laboratorio limita el rol.** Provisionar por un canal
privado autorizado `/etc/pedidos360/ev3/webpay.credentials` con propietario
`root`, modo `0600` y los dos campos `WEBPAY_COMMERCE_CODE` y
`WEBPAY_API_KEY` en formato `NOMBRE=valor`. Agregar `--source host-file`
a `--dry-run` y `--apply`. Cargar los valores fuera del historial de shell y
de sesiones grabadas. Tanto `pago.env` como el entorno Docker son accesibles
para administradores de la EC2. Evitar compartir sus volcados.

## Recuperación y rollback

```bash
python3 deploy/aws/webpay.py --status
python3 deploy/aws/webpay.py --recover
python3 deploy/aws/webpay.py --rollback
```

- **Antes de iniciar el candidato.** Un fallo recuperable restaura el
  contenedor anterior y los bytes originales de `pago.env`.
  `--recover` completa esa restauración si la sesión se interrumpió.
- **Después de solicitar el arranque.** El candidato pudo recibir tráfico
  aunque haya fallado SSM, el health o el Target Group. `--recover` recupera
  el mismo contenedor Webpay. Corregir primero la causa si el error persiste.
  Si el cliente se desconectó, consultar el Command ID de SSM para saber si
  el comando sigue ejecutándose antes de invocar recuperación.
- **Rollback después del arranque.** Ejecutar en ventana de mantenimiento
  y confirmar que esta EC2 es el único escritor de Webpay para el RDS.
  El script necesita `psql` en la EC2 y usa el datasource del contenedor.
  Detiene el candidato, ejecuta una consulta de solo lectura sobre
  `public.webpay_transaction` y `public.payment`, y restaura el anterior
  únicamente si la consulta demuestra la ausencia de transacciones Webpay.
  Ante registros o una consulta inconclusa, vuelve a iniciar el candidato.
  Con datos históricos o una configuración PostgreSQL personalizada, conservar
  Webpay habilitado y conciliar con el procedimiento operativo del equipo.

El rollback conserva PostgreSQL y las migraciones Flyway aplicadas. La
comprobación PostgreSQL usa TLS y admite una URL JDBC de un solo host con
`sslmode=require`, `verify-ca` o `verify-full`. Con verificación de CA, el
certificado debe estar disponible para `psql` en la EC2.

## Pruebas

```bash
python3 -B -m unittest discover -s deploy/aws/tests -v
```

GitHub Actions ejecuta estas pruebas aisladas con Docker, AWS y PostgreSQL
simulados en los límites del script. El workflow de prueba carece de rol AWS
y los cambios en `deploy/aws` no disparan una publicación GHCR nueva.
