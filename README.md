# StockMarket Bot (v1)

API modular para geração de sinais de compra/venda baseada na estratégia HA + Nadaraya-Watson + MKR + Trend Meter, com `paper trading` por padrão e suporte opcional a broker real via feature-flag.

## Objetivos da v1

- Estrutura modular por domínio.
- Regras de trading separadas por arquivo.
- Execução local com validação (sem ordens reais por padrão).
- Preparado para integração futura com APIs de corretoras.

## Arquitetura

- `src/api`: endpoints FastAPI.
- `src/core/models`: entidades e enums de domínio.
- `src/core/ports`: contratos (broker, market data).
- `src/indicators`: cálculo dos indicadores.
- `src/rules`: regras isoladas por arquivo (buy/sell/exit).
- `src/strategies`: orquestração de regras da estratégia.
- `src/services`: engine de sinal, execução e runtime.
- `src/adapters/brokers`: `paper_broker` (simulação) e `alpaca_broker` (real).
- `src/adapters/market_data`: feed CSV para replay.
- `src/infra`: configuração e store in-memory.

## Regras implementadas (arquivos separados)

### Buy

- `rules/buy/body_below_nw_lower.py`
- `rules/buy/confirm_next_body_below_nw_lower.py`
- `rules/buy/mkr_green.py`
- `rules/buy/trend_meter_all_green.py`

### Sell

- `rules/sell/body_above_nw_upper.py`
- `rules/sell/confirm_next_body_above_nw_upper.py`
- `rules/sell/mkr_red.py`
- `rules/sell/trend_meter_all_red.py`

### Exit

- `rules/exit/close_buy_on_mkr_red.py`
- `rules/exit/close_sell_on_mkr_green.py`

## Rodar localmente

O app carrega automaticamente o arquivo `.env` da raiz do projeto no startup.

```bash
poetry install
poetry run uvicorn api.app:app --app-dir src --reload
```

API em `http://127.0.0.1:8000`.
Swagger em `http://127.0.0.1:8000/docs`.

## Modo de execução

Por padrão:

- `TRADING_MODE=paper`
- `DEFAULT_ORDER_QTY=1.0`
- `BROKER_PROVIDER=paper`
- `ALLOW_LIVE_TRADING=false`
- `NW_MULT=3.0` (valor do PDF)
- `REQUIRE_CONFIRMATION=true`
- `REQUIRE_TREND_METER=true`
- `REQUIRE_MKR_ALIGNMENT=true`

### Alpaca paper account

Se você quiser que os sinais enviados por `POST /v1/candles` virem ordens na sua conta paper da Alpaca, use:

- `TRADING_MODE=paper`
- `BROKER_PROVIDER=alpaca`
- `ALPACA_API_KEY=...`
- `ALPACA_API_SECRET=...`
- `ALPACA_BASE_URL=https://paper-api.alpaca.markets`

Nesse modo, os endpoints operacionais usam a Alpaca paper account. Os endpoints de `replay` e `backtest/report` continuam locais para não contaminar a conta paper com backtest histórico.

### Live trading (Alpaca) com trava de segurança

Para habilitar ordens reais, você precisa setar explicitamente:

- `TRADING_MODE=live`
- `ALLOW_LIVE_TRADING=true`
- `BROKER_PROVIDER=alpaca`
- `ALPACA_API_KEY=...`
- `ALPACA_API_SECRET=...`
- `ALPACA_BASE_URL=...` (ex: `https://api.alpaca.markets`)

Se `ALLOW_LIVE_TRADING` não estiver `true`, o sistema bloqueia execução real.

### Presets sugeridos

Os presets abaixo foram validados com dados da Alpaca no periodo de `2026-03-17` ate `2026-03-24`, sempre com `VALIDATION_INITIAL_CAPITAL=10000`.

- `.env.balanced.example`: `AAPL`, `15Min`, `NW_MULT=0.75`, `REQUIRE_CONFIRMATION=false`, `REQUIRE_TREND_METER=false`, `REQUIRE_MKR_ALIGNMENT=true`. Nesse recorte gerou `3` sinais e `net_profit=2.57`.
- `.env.aggressive.example`: `AAPL`, `5Min`, `NW_MULT=0.75`, `REQUIRE_CONFIRMATION=false`, `REQUIRE_TREND_METER=false`, `REQUIRE_MKR_ALIGNMENT=false`. Nesse recorte gerou `78` sinais e `net_profit=2.78`.
- A matriz conservadora com confirmacao, Trend Meter e MKR ligados ficou em `0` sinais para `AAPL`, `NVDA` e `TSLA` em `5Min`, `15Min` e `1Hour`.

Uso rapido:

```bash
cp .env.balanced.example .env
# ou
cp .env.aggressive.example .env
```

## Stream de preco real (online)

1. Preencha suas credenciais no arquivo `.env` (use `.env.example`, `.env.balanced.example` ou `.env.aggressive.example` como base).
2. Suba a API local:

```bash
poetry run uvicorn api.app:app --app-dir src --reload
```

3. Em outro terminal, rode o stream da Alpaca para enviar candles em tempo real para `POST /v1/candles`:

```bash
./scripts/run_alpaca_stream.sh
```

O script usa estas variaveis do `.env`:

- `NW_BANDWIDTH` (default: `8.0`, controla a suavizacao base do envelope)
- `NW_MULT` (default do PDF: `3.0`; em acoes Alpaca pode fazer sentido reduzir para `1.5`)
- `MKR_BANDWIDTH` (default: `9.0`, controla a suavizacao do MKR)
- `REQUIRE_CONFIRMATION` (`false` afrouxa a entrada removendo a exigencia de 2 candles)
- `REQUIRE_TREND_METER` (`false` ignora o gate do Trend Meter na entrada)
- `REQUIRE_MKR_ALIGNMENT` (`true` mantem o filtro do MKR; pode ser desligado para testes mais agressivos)
- `ALPACA_API_KEY`
- `ALPACA_API_SECRET`
- `ALPACA_ASSET_CLASS` (`stocks` ou `crypto`)
- `ALPACA_BAR_TIMEFRAME` (default: `5Min`)
- `SYMBOL` (stocks: `AAPL`, crypto: `BTC/USD`)
- `API_INGEST_URL` (default: `http://127.0.0.1:8000/v1/candles`)
- `ALPACA_DATA_URL` (default stocks: `https://data.alpaca.markets/v2/stocks/bars`)
- `POLL_INTERVAL_SECONDS` (default: `5`)
- `UNCHANGED_BAR_WARN_EVERY_POLLS` (default: `12`, imprime status enquanto espera o proximo candle)

Observacao sobre `EURUSD`:

- atualmente a Alpaca pode retornar vazio para `EURUSD`/`EUR/USD` nesses endpoints;
- se precisar validar exatamente o ativo do PDF (`EURUSD` em 5m), use um feed FX (ex.: OANDA).

## Validacao objetiva com Alpaca (historico + backtest)

Use este fluxo para validar a abordagem sem depender de ficar esperando sinal ao vivo:

1. Suba a API local:

```bash
poetry run uvicorn api.app:app --app-dir src --reload
```

2. Em outro terminal, rode:

```bash
./scripts/run_alpaca_validation.sh
```

O script:

- baixa candles historicos da Alpaca (`SYMBOL` + `ALPACA_BAR_TIMEFRAME`);
- salva CSV em `VALIDATION_OUTPUT_DIR`;
- chama `POST /v1/backtest/report`;
- nao envia ordens para a Alpaca paper account;
- imprime no terminal: `action_signals`, `filled_orders`, `win_rate`, `net_profit`, `max_drawdown`;
- imprime diagnostico de regras (pass-rate por regra de buy/sell), para identificar gargalos.

Variaveis de validacao (arquivo `.env`):

- `NW_BANDWIDTH` (suavizacao base do envelope de Nadaraya-Watson)
- `NW_MULT` (ajusta a largura do envelope usado pela API local)
- `MKR_BANDWIDTH` (suavizacao do Multi Kernel Regression)
- `REQUIRE_CONFIRMATION`
- `REQUIRE_TREND_METER`
- `REQUIRE_MKR_ALIGNMENT`
- `VALIDATION_LOOKBACK_DAYS` (default: `7`)
- `VALIDATION_REPORT_PERIOD` (`day|week|month`)
- `VALIDATION_QTY` (qty simulada para backtest)
- `VALIDATION_INITIAL_CAPITAL` (capital base usado para `equity_curve` e `max_drawdown_pct`)
- `VALIDATION_STOCK_FEED` (default: `iex`, recomendado para evitar bloqueio de SIP)

## Otimizacao de parametros com Alpaca

O projeto agora inclui uma rotina local de otimizacao em grade com refinamento opcional, sempre usando candles historicos da Alpaca e backtest em `PaperBroker` local.

Exemplo curto:

```bash
poetry run python scripts/optimize_alpaca_params.py \
  --symbols AAPL \
  --timeframes 5Min,15Min \
  --lookback-days 30 \
  --nw-bandwidths 8.0,10.0 \
  --nw-mults 1.5,1.0,0.75 \
  --mkr-bandwidths 9.0,11.0
```

Saidas:

- cache de candles em `data/cache/alpaca/`
- `all_trials.csv` com todas as combinacoes avaliadas
- `best_params.json` com a melhor combinacao elegivel in-sample (ou fallback para a melhor geral)
- `operational_params.json` com a selecao canonica para consumo operacional
- `summary.json` com datasets, restricoes e melhores resultados por dataset

Restricoes e score da rotina base:

- filtra por `min_trades`, `min_profit_factor` e `max_drawdown_pct`
- ranqueia por `net_profit - drawdown_weight * max_drawdown + profit_factor_weight * profit_factor`
- pode refinar os melhores candidatos com `--refine-top-k` e passos numericos

Walk-forward / out-of-sample:

```bash
poetry run python scripts/optimize_alpaca_params.py \
  --symbols AAPL \
  --timeframes 5Min \
  --lookback-days 30 \
  --nw-bandwidths 8.0,10.0 \
  --nw-mults 1.5,1.0,0.75 \
  --mkr-bandwidths 9.0,11.0 \
  --walk-forward \
  --wf-train-bars 250 \
  --wf-test-bars 50 \
  --wf-step-bars 50
```

Nesse modo, o script otimiza cada janela de treino, escolhe o melhor candidato elegivel e executa esse setup apenas na janela seguinte de teste. Em paralelo, ele tambem monta uma leaderboard fixa de candidatos pela soma do desempenho out-of-sample ao longo das janelas de teste. Saidas adicionais:

- `walk_forward_trials.csv` com o setup escolhido por janela e o resultado out-of-sample
- `walk_forward_candidates_<symbol>_<timeframe>.csv` com o ranking agregado dos candidatos em out-of-sample
- `walk_forward_summary.json` com agregacao por dataset e o melhor candidato walk-forward
- `walk_forward_<symbol>_<timeframe>_equity_curve.csv` com a curva de capital dos testes em sequencia
- `operational_params.json` regravado com o melhor candidato walk-forward por dataset (ou `overall_fallback` se nenhum cumprir as restricoes agregadas)

Leitura pratica: se o melhor setup na janela inteira parecer forte, mas o walk-forward degradar muito, isso e um sinal direto de fragilidade ou overfit. O arquivo `best_params.json` continua sendo o melhor ranking in-sample; o arquivo `operational_params.json` passa a ser a referencia canonica para execucao quando o walk-forward estiver habilitado. Se nenhum candidato cumprir as restricoes agregadas, o resumo marca `overall_fallback` para indicar que o melhor ranking ainda ficou abaixo do filtro desejado.

## Endpoints

- `GET /health`
- `POST /v1/candles`
- `POST /v1/replay`
- `POST /v1/backtest/report`
- `GET /v1/signals`
- `GET /v1/orders`
- `GET /v1/positions`
- `POST /v1/reset`

## Replay via CSV

`/v1/replay` é permitido apenas em `TRADING_MODE=paper`.

Formato esperado do CSV:

- colunas: `timestamp,open,high,low,close,volume`
- `timestamp` em ISO-8601 (ex: `2026-01-01T10:00:00+00:00`)

Exemplo:

```bash
curl -X POST http://127.0.0.1:8000/v1/replay \
  -H "Content-Type: application/json" \
  -d '{
    "csv_path": "scripts/sample_candles.csv",
    "symbol": "PETR4",
    "qty": 1,
    "initial_capital": 10000
  }'
```

Resposta do replay inclui:

- `win_rate`
- `max_drawdown` e `max_drawdown_pct`
- `equity_curve` (curva de equity candle a candle, iniciando em `initial_capital`)

## Backtest Report + CSV

Endpoint:

- `POST /v1/backtest/report`

Request:

- `csv_path`: caminho do CSV
- `symbol` (opcional): símbolo default se o CSV não tiver coluna `symbol`
- `qty` (opcional)
- `initial_capital` (opcional, default `10000`)
- `period`: `day`, `week` ou `month`
- `output_dir`: pasta para export do CSV da curva de equity

Resposta inclui:

- `summary`: resumo completo do replay
- `grouped_metrics`: métricas agregadas por `symbol + period`
- `equity_curve_csv_path`: caminho absoluto do CSV exportado

Exemplo:

```bash
curl -X POST http://127.0.0.1:8000/v1/backtest/report \
  -H "Content-Type: application/json" \
  -d '{
    "csv_path": "scripts/sample_candles.csv",
    "symbol": "PETR4",
    "initial_capital": 10000,
    "period": "day",
    "output_dir": "reports/backtests"
  }'
```

## Testes

```bash
poetry run pytest
```
# stockmarket_bot
