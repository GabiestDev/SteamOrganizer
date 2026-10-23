# steamorganizer

Organizador de biblioteca Steam em português (pt-BR). Um único executável bash para Linux que classifica seus jogos em coleções bem nomeadas, com perguntas interativas no startup via [gum](https://github.com/charmbracelet/gum).

## Requisitos

- `bash`
- `gum` (interface interativa)
- `python3`
- `steam` (cliente instalado)

### Fedora / RHEL
```bash
sudo dnf install gum python3 steam
```

### Ubuntu / Debian
```bash
sudo apt install gum python3 steam
```

### Arch / CachyOS
```bash
sudo pacman -S gum python steam
```

Para o **modo completo** (captura 100% da biblioteca, incluindo família/empréstimo):
```bash
pip install websocket-client vdf
```

## Uso

```bash
chmod +x steamorganizer
./steamorganizer
```

O script fará tudo automaticamente:

1. Detecta sua instalação Steam (nativo, Flatpak, Snap, etc.)
2. Faz **todas as perguntas de uma vez** no início:
   - Modo rápido (apenas jogos com tempo de jogo) ou **completo** (todos, incluindo família)
   - Quais categorias criar (todas marcadas por padrão)
   - Nome e emoji personalizados para cada categoria
   - Coleção pai **Franquias** (união de jogos de mesma franquia)
   - Coleção **Instalados localmente no topo**
3. Faz **backup automático** antes de modificar
4. Fecha a Steam, classifica os jogos e grava o `cloud-storage-namespace-1.json`
5. Oferece reiniciar a Steam no final

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
```
userdata/<id>/config/cloudstorage/cloud-storage-namespace-1.json
```

O script lê esse arquivo, adiciona/atualiza as coleções com os appids classificados e reescreve o JSON de forma idempotente (não cria duplicatas).

## Backup

Antes de qualquer alteração, o script copia os arquivos originais para:
```
/tmp/steamorganizer_backup_YYYYMMDD_HHMMSS/
```

## Limitações

- O Steam **não suporta coleções aninhadas** (pasta dentro de pasta). O que o script faz é criar a coleção pai com todos os jogos de franquia juntos, mais coleções individuais agrupadas por prefixo na barra lateral.
- Para editar o arquivo cloud-storage, a Steam precisa estar **fechada** (o script fecha com `steam -shutdown`).

## Licença

MIT — use, modifique e distribua livremente.