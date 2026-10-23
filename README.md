# steamorganizer

Organizador de biblioteca Steam em português (pt-BR). Script único em **Python puro** que funciona tanto no **Windows** quanto no **Linux**, classificando seus jogos em coleções bem nomeadas com perguntas interativas no startup.

## Requisitos

- Python 3
- `gum` (opcional — interface interativa; se não tiver, usa `input()` normalmente)
- `vdf`, `websocket-client`, `psutil` (instalados automaticamente no primeiro uso se faltarem; `vdf` é opcional graças ao parser VDF puro embutido)

## Uso

### Modo interativo

```bash
python steamorganizer.py
```

### Modo linha de comando (CLI)

```bash
python steamorganizer.py --steam-path "/caminho/da/steam" --user 376470568 --full --dry-run
python steamorganizer.py --steam-path "/caminho/da/steam" --full
python steamorganizer.py --no-gum --full
```

### Argumentos CLI

| Argumento | Descrição |
|-----------|-----------|
| `--steam-path` | Caminho da instalação Steam |
| `--user` | SteamID3 da conta (ex: 376470568) |
| `--full` | Modo completo (inclui família/empréstimo) |
| `--dry-run` | Apenas visualizar, não grava nada |
| `--no-gum` | Desativar gum, usar input() |
| `--no-restart` | Não reiniciar a Steam ao final |

O script fará tudo automaticamente:

1. Detecta sua instalação Steam (vários caminhos possíveis por SO, incluindo registro do Windows e varredura de unidades)
2. Oferece **modo dry-run** (apenas visualizar, não grava nada)
3. Avisa que a Steam será fechada e pede confirmação
4. Faz **backup automático** antes de modificar
5. Fecha a Steam graceful (`steam -shutdown`) antes de gravar
6. Classifica os jogos em **paralelo** (`ThreadPoolExecutor`)
7. Grava o `cloud-storage-namespace-1.json` com **rollback automático** em caso de falha
8. **Remove coleções órfãs** (antigas que não fazem mais parte da nova organização)
9. **Valida o JSON gravado** para garantir integridade
10. Oferece reiniciar a Steam no final

## O que ele organiza

Categorias disponíveis (personalizáveis):

- Ação, Aventura, Cartas & Tabuleiro, Casual & Puzzle, Co-op, Competitivo
- Corrida, Demos & Betas, Esportes, Estratégia, Ferramentas, Indie & Retrô
- Jogando Agora, Luta, MMO, RPG, Simulação, Sobrevivência, Terror
- Trilhas & Vídeos, VR, Outros

Plus:
- **Franquias 📂** — coleção pai com todos os jogos de franquias (união)
- **🧟 Resident Evil**, **🧪 Half-Life**, **🧱 LEGO**, etc. — coleções individuais por franquia (apenas ícone + nome, sem prefixo "Franquia:")
- **Instalados localmente** — fica sempre no topo

## Funcionamento

O Steam armazena coleções modernas em:

- **Windows:** `%PROGRAMFILES(X86)%\Steam\userdata\<id>\config\cloudstorage\cloud-storage-namespace-1.json`
- **Linux:** `~/.local/share/Steam/userdata/<id>/config/cloudstorage/cloud-storage-namespace-1.json`

O script lê esse arquivo, adiciona/atualiza as coleções com os appids classificados e reescreve o JSON de forma idempotente (não cria duplicatas).

## Backup

Antes de qualquer alteração, o script copia os arquivos originais para:

- **Windows:** `%TEMP%\steamorganizer_backup_YYYYMMDD_HHMMSS\`
- **Linux:** `/tmp/steamorganizer_backup_YYYYMMDD_HHMMSS/`

## Limitações

- O Steam **não suporta coleções aninhadas** (pasta dentro de pasta). O que o script faz é criar a coleção pai com todos os jogos de franquia juntos, mais coleções individuais agrupadas por prefixo na barra lateral.
- Para editar o arquivo cloud-storage, a Steam precisa estar **fechada** (o script fecha com `steam -shutdown`).

## Licença

MIT — use, modifique e distribua livremente.