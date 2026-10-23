# steamorganizer

Organizador de biblioteca Steam em português (pt-BR). Script único em **Python puro** que funciona tanto no **Windows** quanto no **Linux**, classificando seus jogos em coleções bem nomeadas com perguntas interativas no startup.

## Requisitos

- Python 3
- `gum` (opcional — interface interativa; se não tiver, usa `input()` normalmente)
- `vdf` e `websocket-client` (instalados automaticamente no primeiro uso se faltarem)

### Instalar dependências

O script tenta instalar sozinho `vdf` e `websocket-client` via `pip` no startup. Se não conseguir, rode manualmente:

```powershell
# Windows
pip install vdf websocket-client
```

```bash
# Linux
pip install vdf websocket-client
```

Para usar a interface interativa com `gum`, instale-o no seu sistema (não é instalável via pip):

- **Fedora / RHEL:** `sudo dnf install gum`
- **Ubuntu / Debian:** `sudo apt install gum`
- **Arch / CachyOS:** `sudo pacman -S gum`

## Uso

```bash
python steamorganizer.py
```

O script fará tudo automaticamente:

1. Detecta sua instalação Steam (vários caminhos possíveis por SO)
2. Faz **todas as perguntas de uma vez** no início:
   - Modo rápido (apenas jogos com tempo de jogo) ou **completo** (todos, incluindo família/empréstimo)
   - Quais categorias criar (todas marcadas por padrão)
   - Nome e emoji personalizados para cada categoria
   - Coleção pai **Franquias** (união de jogos de mesma franquia)
   - Coleção **Instalados localmente no topo**
3. Faz **backup automático** antes de modificar
4. Fecha a Steam, classifica os jogos e grava o `cloud-storage-namespace-1.json`
5. Oferece reiniciar a Steam no final

## Gerar executável .exe (Windows)

Para entregar um único `.exe` para Windows:

```powershell
pip install pyinstaller
pyinstaller --onefile --noconsole steamorganizer.py
```

O executável ficará em `dist/steamorganizer.exe`.

## O que ele organiza

Categorias disponíveis (personalizáveis):

- Ação, Aventura, Cartas & Tabuleiro, Casual & Puzzle, Co-op, Competitivo
- Corrida, Demos & Betas, Esportes, Estratégia, Ferramentas, Indie & Retrô
- Jogando Agora, Luta, MMO, RPG, Simulação, Sobrevivência, Terror
- Trilhas & Vídeos, VR, Outros

Plus:
- **Franquias 📂** — coleção pai com todos os jogos de franquias detectadas (Resident Evil, Half-Life, Fallout, GTA, Warhammer, Counter-Strike, etc.)
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