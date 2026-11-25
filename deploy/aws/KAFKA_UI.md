# Kafka UI para Pedidos360 EV3

El broker Kafka funciona como un servicio independiente en ECS Fargate. Los microservicios acceden al broker por el balanceador privado. Kafbat UI proporciona el panel de observación en un contenedor aparte en una EC2 con capacidad disponible. Lee el mismo broker que utiliza la aplicación. La revisión fija Kafbat UI 1.5.1 por su digest publicado.

## Activar en AWS

En CloudShell del laboratorio, con el archivo privado `~/kafka_recovery.py` que utiliza el verificador de conectividad:

```bash
cd "$HOME/pedidos360-ops-pago" &&
git pull --ff-only origin ev3/webpay-integracion &&
python3 deploy/aws/kafka_ui.py --apply
```

El script valida la cuenta, consulta por SSM la memoria libre de las EC2 candidatas (Productos, Carrito, Analytics y Fidelización) y comprueba que el panel puede listar los tópicos del broker. El panel escucha en `127.0.0.1:18090` de la instancia, con el clúster en modo de solo lectura. La operación reutiliza el contenedor si ya tiene la configuración esperada.

Para revisar el panel después de reiniciar el laboratorio:

```bash
python3 deploy/aws/kafka_recovery.py --verify &&
python3 deploy/aws/kafka_ui.py --verify
```

Si el panel quedó detenido, `--apply` vuelve a iniciarlo. El estado del broker y el estado del panel se comprueban por separado.

## Abrir el panel en Windows

En PowerShell de tu PC, usa AWS CLI y el complemento de Session Manager con una sesión válida del laboratorio. Si el laboratorio entrega un archivo de credenciales temporales, puedes elegirlo con `AWS_SHARED_CREDENTIALS_FILE` en esa terminal. Sustituye `ID-EC2` por el ID que imprimió el script en la línea «Kafka UI · EC2».

```powershell
aws ssm start-session --region us-east-1 --target ID-EC2 --document-name AWS-StartPortForwardingSession --parameters 'portNumber=18090,localPortNumber=18090'
```

Mientras el túnel esté abierto, entra a [Kafbat UI](http://127.0.0.1:18090/) en Firefox. Selecciona **pedidos360 → Topics** y busca `producto.interaccion.v1`, `carrito.actualizado.v1` o `pago.aprobado.v1`. Para revisar el procesamiento, abre **Consumers** y mira los grupos y su retraso. Una interacción de catálogo genera evidencia en el tópico de Productos y en **Mi actividad**.

- [Instalar AWS CLI en Windows](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- [Instalar el complemento de Session Manager](https://docs.aws.amazon.com/systems-manager/latest/userguide/install-plugin-windows.html)
- [Documentación de Kafbat UI](https://ui.docs.kafbat.io/)
