# Imágenes AWS de Pedidos360 EV3

Publicación del 18/11/2026 en `ev3/integracion-integral`. Las diez ejecuciones
de publicación pasaron y cada tag versionado resolvió al SHA256 indicado en
GHCR. Las referencias incluyen el digest del índice de imagen empleable con
`docker pull`. La sustitución de contenedores en EC2 queda a cargo del operador.

[Checklist y comandos de despliegue en GitHub](https://github.com/ZorVaK749/fazbear-pago/blob/ev3/integracion-integral/docs/ENTREGA_AWS_EV3.md)

| Servicio | Commit | Actions | Imagen por digest |
| --- | --- | --- | --- |
| Analytics | `3bbd0cb` | [44362070039](https://github.com/ZorVaK749/fazbear-analytics-recommendations/actions/runs/44362070039) | `ghcr.io/zorvak749/fazbear-analytics-recommendations@sha256:7e9d36303dda9fdbddf6719d62f38a5a7975f258db54f83edb0ae85cdc956aff` |
| Carrito | `f4fc72d` | [44362076984](https://github.com/ZorVaK749/fazbear-carrito/actions/runs/44362076984) | `ghcr.io/zorvak749/fazbear-carrito@sha256:7377afa7f63d068069b94f0a45f2cf754866db4a24222fb070c166a675f11a45` |
| Fidelización | `309561c` | [44362087350](https://github.com/ZorVaK749/fazbear-fidelizacion/actions/runs/44362087350) | `ghcr.io/zorvak749/fazbear-fidelizacion@sha256:627283e9b8b68869ecd9ec8498bdf9423e9ef68e13f9f7c052eff486bd33b2c0` |
| Frontend | `27905eb` | [44362095542](https://github.com/ZorVaK749/fazbears-frontend/actions/runs/44362095542) | `ghcr.io/zorvak749/fazbears-frontend@sha256:21cf32d947fd1793b715177602289ec668ec4b52e85e81a71e3cf2e9aa2b9ffb` |
| Notificaciones | `82983ba` | [44362105821](https://github.com/ZorVaK749/fazbear-notificaciones/actions/runs/44362105821) | `ghcr.io/zorvak749/fazbear-notificaciones@sha256:b8cc115d45e916b9c17b063eabca1ccb2345c91b17a82fc298e06d4d5aa9b8aa` |
| Orden | `8b35c47` | [44362114205](https://github.com/ZorVaK749/fazbear-orden/actions/runs/44362114205) | `ghcr.io/zorvak749/fazbear-orden@sha256:266a25e476a5feaf54a5921d0ed25c6be477492f222783f3e3740e9aebc5c8ea` |
| Pago | `84d8aca` | [44363569697](https://github.com/ZorVaK749/fazbear-pago/actions/runs/44363569697) | `ghcr.io/zorvak749/fazbear-pago@sha256:7185f4a6b38d6e28a2f9cb7de5dcf7610c568d0d44cd26bd208ab8e4d87a3a3d` |
| Pedidos | `0913fb5` | [44362124109](https://github.com/ZorVaK749/fazbears-pedidos/actions/runs/44362124109) | `ghcr.io/zorvak749/fazbears-pedidos@sha256:2ee37f89758573b1d07d620ba2e4430553885da152455efe53d5e3fa1974d765` |
| Productos | `c82cc33` | [44363960937](https://github.com/ZorVaK749/fazbears-productos/actions/runs/44363960937) | `ghcr.io/zorvak749/fazbears-productos@sha256:cf5779c2fa85e461a222f826035b874b6f2fa312e47190077a3e2e61f6447c1f` |
| Reportes | `24b14ea` | [44365080009](https://github.com/ZorVaK749/fazbear-reportes/actions/runs/44365080009) | `ghcr.io/zorvak749/fazbear-reportes@sha256:a874105db34f64563604049acdb772937016807d22164198c1477238fa234865` |

Por EC2, copiar la referencia de su servicio de la tabla, consultar el
contenedor actual y traer la imagen antes de la ventana de corte.

```bash
git switch ev3/integracion-integral
git pull --ff-only origin ev3/integracion-integral
docker pull "$IMAGE"   # IMAGE es la referencia completa de su servicio en la tabla.
```

En Productos, completar primero el respaldo y el cotejo de los 23 productos con
su stock vivo. Mantener el origen activo hasta comprobar la restauración. La
imagen EV3 desactiva la semilla automática en AWS.

## Pruebas

- Pedidos ejecutó 67 pruebas sin fallos ni omisiones, incluidas idempotencia y
  concurrencia en H2 de archivo y PostgreSQL.
- Productos registró 55 casos, 54 ejecutados y uno omitido por su configuración
  de CI. Pasaron el respaldo y restauración sintéticos con stock variable y el
  encolado de 23 snapshots en el perfil AWS.
- Angular aprobó sus nueve archivos de pruebas y el build de producción.
- Reportes verificó la exigencia del app role configurado y del scope delegado.
- La prueba integral pasó los preflights en los servicios, el flujo de compra
  simulada, el pedido único, los eventos Kafka, las recomendaciones y los
  movimientos FazCoins. Usó identidades y datos sintéticos en GitHub Actions.
  [Prueba integral con las revisiones finales de los servicios del flujo](https://github.com/ZorVaK749/fazbear-pago/actions/runs/44363569763/attempts/2)

Antes de habilitar tráfico, faltan el respaldo vivo de Productos y el cotejo de
su restauración, el ajuste de CORS en el Gateway, el destino de Fidelización y
la validación con Entra real en AWS.
