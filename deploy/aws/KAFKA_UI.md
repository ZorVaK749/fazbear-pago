# Kafka UI para Pedidos360 EV3

El broker Kafka funciona como un servicio independiente en ECS Fargate. Los microservicios acceden al broker por el balanceador privado. Kafdrop proporciona el panel de observación en un contenedor aparte en una EC2 con capacidad disponible. Lee el mismo broker que utiliza la aplicación. Se usa Kafdrop 4.3.1, fijado por digest, con 256 MiB de memoria y medio CPU como límites.

## Elegir una EC2 respetando el límite del laboratorio

El diseño usa hasta nueve EC2 para Pago, Carrito, Productos, Analytics, Fidelización, Notificaciones, Orden, Reportes y Pedidos. Frontend y Kafka se inventarían como servicios ECS. Kafka UI y su proxy pueden compartir una EC2 con un servicio existente.

```bash
cd "$HOME/pedidos360-ops-pago" &&
git pull --ff-only origin ev3/webpay-integracion &&
python3 deploy/aws/kafka_ui.py --inventory
```

El inventario consulta el tipo de instancia, la memoria disponible, la IPv4 y si tiene una Elastic IP. Comprueba TCP al broker desde las EC2 identificadas y detecta ocupación de los puertos del proxy. Compara la capacidad disponible con los límites de 256 MiB para Kafdrop y 96 MiB para Caddy, dejando margen para el microservicio que ya corre ahí. Una EC2 con Kafdrop en ejecución solo necesita capacidad adicional para el proxy.

## Activar en AWS

En CloudShell del laboratorio, con el archivo privado `~/kafka_recovery.py` que utiliza el verificador de conectividad:

```bash
cd "$HOME/pedidos360-ops-pago" &&
git pull --ff-only origin ev3/webpay-integracion &&
python3 deploy/aws/kafka_ui.py --apply
```

El script valida la cuenta, consulta por SSM la memoria libre de las EC2 candidatas (Productos, Carrito, Analytics y Fidelización) y comprueba que el panel puede listar los tópicos del broker. El panel escucha en `127.0.0.1:18090` de la instancia. La interfaz tiene deshabilitada la creación y eliminación de tópicos y el envío de mensajes. La operación reutiliza el contenedor si ya tiene la configuración esperada.

Para revisar el panel después de reiniciar el laboratorio:

```bash
python3 deploy/aws/kafka_recovery.py --verify &&
python3 deploy/aws/kafka_ui.py --verify
```

Si el panel quedó detenido, `--apply` vuelve a iniciarlo. El estado del broker y el estado del panel se comprueban por separado.

Si la verificación falla, `python3 deploy/aws/kafka_ui.py --diagnose` muestra el estado de Docker, la conexión TCP al broker, los puertos en escucha y los resultados HTTP de la portada y de `/topic`.

## Abrir por la IPv4 pública de la EC2

El Compose del proxy se ejecuta en la misma EC2 que Kafdrop. Antes de levantarlo, confirma que Kafdrop lista los tópicos en `127.0.0.1:18090`, que esa EC2 tiene IPv4 pública, que tiene Docker Compose y que los puertos 80 y 18443 están disponibles. Usa la IPv4 pública y privada de la misma instancia que muestra la consola de EC2.

Para mantener una dirección estable entre reinicios, usa la Elastic IP de esa EC2 si ya tiene una. En CloudShell, comprueba las direcciones en la región antes de decidir si necesitas asociar otra:

```bash
aws ec2 describe-addresses --region us-east-1 --query 'Addresses[].{IPv4:PublicIp,Asignacion:AllocationId,EC2:InstanceId,Interfaz:NetworkInterfaceId}' --output table
```

Si la EC2 tiene solo una IPv4 pública dinámica, asociar una Elastic IP reemplaza esa dirección. Revisa primero qué integraciones usan la IP pública actual. Una Elastic IP tiene costo y ocupa cuota de la región. La configuración también funciona con la IPv4 pública dinámica, con un certificado nuevo si cambia.

En el grupo de seguridad de la EC2 del panel, habilita TCP/18443 solo desde la IPv4 pública del equipo de la presentación con máscara `/32`. Caddy usa TCP/80 para que Let's Encrypt valide el control de la IP y emita un certificado de duración corta. Durante la emisión, el puerto 80 debe ser accesible desde Internet. El proxy HTTP solo atiende el desafío ACME y redirige al equipo autorizado a HTTPS. Después de emitir el certificado, puedes restringir TCP/80 a la misma IPv4 de la demo o cerrar ese puerto y abrir directamente HTTPS. Una renovación futura vuelve a necesitar la validación.

Al terminar con éxito, `kafka_ui.py --apply` copia los archivos del proxy a `/opt/pedidos360-kafka-ui` de la misma EC2. En la sesión de esa EC2, exporta las tres IPv4 e introduce una contraseña de demo en el prompt. Caddy lee su hash de un archivo de la EC2 con permisos `0600`.

```bash
cd /opt/pedidos360-kafka-ui
export KAFKA_UI_PUBLIC_IPV4=IPv4_PUBLICA_EC2
export KAFKA_UI_PRIVATE_IPV4=IPv4_PRIVADA_EC2
export KAFKA_UI_CLIENT_IPV4=IPv4_PUBLICA_DEL_NAVEGADOR
caddy_image='caddy:2.11.9-alpine@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0'
read -rsp 'Contraseña de demo: ' kafka_ui_password
printf '\n'
KAFKA_UI_PASSWORD_HASH=$(printf '%s\n' "$kafka_ui_password" | sudo docker run --rm -i "$caddy_image" caddy hash-password --bcrypt-cost 10)
unset kafka_ui_password
if test -n "$KAFKA_UI_PASSWORD_HASH"; then
  sudo install -m 0600 /dev/null kafka-ui.credentials &&
    printf 'demo %s\n' "$KAFKA_UI_PASSWORD_HASH" | sudo tee kafka-ui.credentials >/dev/null &&
    sudo --preserve-env=KAFKA_UI_PUBLIC_IPV4,KAFKA_UI_PRIVATE_IPV4,KAFKA_UI_CLIENT_IPV4 \
      docker compose -f compose.kafka-ui-proxy.yml up -d
fi
unset KAFKA_UI_PASSWORD_HASH
```

Abre `http://IPv4_PUBLICA_EC2:80/` en Firefox para que redirija a `https://IPv4_PUBLICA_EC2:18443/`. Usa el usuario `demo`. Comprueba que el certificado coincide con esa IPv4, que el navegador pide autenticación y que después aparecen los tópicos. Una nueva IPv4 pública requiere actualizar el proxy y emitir un certificado para la nueva IP.

Caddy restringe el acceso a la IPv4 indicada, exige una contraseña, reenvía a Kafdrop las consultas GET y HEAD, y filtra las rutas de administración. El puerto de Kafdrop se mantiene en loopback. Para retirar el acceso tras la demo, ejecuta `sudo docker stop pedidos360-ev3-kafka-ui-proxy-proxy-1` y revoca las reglas que agregaste al grupo de seguridad.

## Abrir por Session Manager

En PowerShell de tu PC, usa AWS CLI y el complemento de Session Manager con una sesión válida del laboratorio. Si el laboratorio entrega un archivo de credenciales temporales, puedes elegirlo con `AWS_SHARED_CREDENTIALS_FILE` en esa terminal. Sustituye `ID-EC2` por el ID que imprimió el script en la línea «Kafka UI · EC2».

```powershell
aws ssm start-session --region us-east-1 --target ID-EC2 --document-name AWS-StartPortForwardingSession --parameters 'portNumber=18090,localPortNumber=18090'
```

Mientras el túnel esté abierto, entra a [Kafka UI](http://127.0.0.1:18090/) en Firefox. Busca `producto.interaccion.v1`, `carrito.actualizado.v1` o `pago.aprobado.v1` en **Topics**. Abre un tópico para revisar sus mensajes y el retraso de sus grupos de consumidores. Una interacción de catálogo genera evidencia en el tópico de Productos y en **Mi actividad**.

- [Instalar AWS CLI en Windows](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- [Instalar el complemento de Session Manager](https://docs.aws.amazon.com/systems-manager/latest/userguide/install-plugin-windows.html)
- [Documentación de Kafdrop](https://github.com/obsidiandynamics/kafdrop)
- [Certificados para IP de Let's Encrypt](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability)
- [Elastic IP en EC2](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/elastic-ip-addresses-eip.html)
