# Runs only isolated test JVMs/Testcontainers; never contacts AWS or a live H2 JVM.
param([string]$Workspace = (Resolve-Path "$PSScriptRoot/../../..").Path)
$ErrorActionPreference = 'Stop'
$products = Join-Path $Workspace 'fazbear-productos-ev3-integral'
$cart = Join-Path $Workspace 'fazbear-carrito-ev3-integral'
$analytics = Join-Path $Workspace 'fazbear-analytics-ev3-integral'
foreach ($repo in @($products, $cart, $analytics)) {
    if (-not (Test-Path "$repo/pom.xml")) { throw "Missing integral sibling: $repo" }
}
foreach ($entry in @(@{repo=$products;test='ProductEventsIntegrationTest'}, @{repo=$cart;test='CarritoOutboxIntegrationTests'})) {
    mvn -B -f "$($entry.repo)/pom.xml" "-Dtest=$($entry.test)" '-Dev3.contract.export=true' test
    if ($LASTEXITCODE -ne 0) { throw 'Producer contract export failed' }
}
$env:EV3_PRODUCER_CONTRACTS = 'true'
$env:PRODUCTOS_CONTRACT_FILE = "$products/target/contracts/productos.json"
$env:CARRITO_CONTRACT_FILE = "$cart/target/contracts/carrito.json"
try {
    mvn -B -f "$analytics/pom.xml" '-Dtest=AnalyticsIntegrationTest' test
    if ($LASTEXITCODE -ne 0) { throw 'Consumer contract integration failed' }
} finally {
    Remove-Item Env:EV3_PRODUCER_CONTRACTS, Env:PRODUCTOS_CONTRACT_FILE, Env:CARRITO_CONTRACT_FILE -ErrorAction SilentlyContinue
}
