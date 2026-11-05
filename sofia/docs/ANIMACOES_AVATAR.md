# Avatar animado da SofIA — quadros individuais HD

O avatar da pagina dedicada reage aos eventos do proprio chat, sem chamadas
adicionais ao n8n ou ao modelo. Nesta etapa ele permanece no painel da analista.
Movimentacao livre pela pagina e um avatar 3D articulado nao fazem parte desta
versao. As poses sao animacoes de imagens, sem sincronizacao labial ou voz nova.

| Evento | Pose |
| --- | --- |
| Em espera | Foto original em alta resolucao com movimento leve |
| Consulta enviada | Bracos cruzados e balao de pensamento com o rotulo Consultando |
| Resposta recebida / texto sendo exibido | Gesto de explicacao |
| Cancelamento em andamento | Postura neutra e rotulo Cancelando; sem balao |
| Cancelamento confirmado ou nova conversa | Repouso |
| Falha ou cancelamento nao confirmado | Postura neutra e rotulo de falha; sem balao |

Esses estados representam o andamento da consulta, nao sentimentos inferidos
pela IA. Antes a pose de pensamento era reutilizada para falhas/cancelamentos;
isso foi removido para nao confundir os estados. O cabecalho mostra Respondendo
enquanto o texto esta sendo exibido e volta para Em espera ao terminar.

O video com audio ao passar o mouse continua disponivel durante o repouso.
Ao iniciar uma consulta, o video para para dar lugar ao estado da consulta.
O botao de pausa no cabecalho do terminal liga/desliga as animacoes e guarda a
preferencia neste navegador. A preferencia de movimento reduzido do sistema
tem prioridade. Sem suporte a canvas ou se a imagem falhar, a foto original
continua sendo exibida. A animacao pausa quando a pagina esta oculta ou o
avatar sai da area visivel.

## Arquivos

- `static/sofia/media/sofia-portrait-transparent.png`: foto original de repouso, 937 x 1678.
- `static/sofia/media/sofia-thinking-crossed-hd-a.png`: bracos cruzados, quadro A, 980 x 1605.
- `static/sofia/media/sofia-thinking-crossed-hd-b.png`: bracos cruzados, quadro B, 980 x 1605.
- `static/sofia/media/sofia-responding-hd-a.png`: resposta, quadro A, 937 x 1679.
- `static/sofia/media/sofia-responding-hd-b.png`: resposta, quadro B, 937 x 1678.
- `static/sofia/avatar-animation.js`: desenho dos quadros e estados visuais.
- `static/sofia/avatar.js`: reproducao do video existente.
- `static/sofia/sofia.js`: emite eventos de consulta e inicio/fim da exibicao
  progressiva de uma resposta.

Os quadros HD foram gerados pela ferramenta integrada de imagens, usando a foto
original como referencia. Cada quadro de continuidade usa o anterior como
referencia para preservar o enquadramento. Os prompts estao registrados em
[sofia_avatar_hd_prompts.json](sofia_avatar_hd_prompts.json).

A folha 3 x 3 do prototipo nao e mais utilizada: seus quadros de aproximadamente
341 x 512 pixels perdiam nitidez ao ampliar. Cada arquivo atual tem resolucao
superior aos 720 x 1280 do video. Isso preserva detalhes de origem, mas nao
transforma a animacao por quadros em um video ou modelo 3D.

O canvas acompanha o tamanho do painel e devicePixelRatio da tela, limitado a
resolucao nativa. ResizeObserver adapta o desenho quando o painel muda de
tamanho. Os arquivos sao carregados uma vez, somente quando as animacoes estao
habilitadas e o sistema nao solicita movimento reduzido. A foto original
continua como fallback se um quadro nao carregar ou tiver resolucao insuficiente.

As excecoes no `.gitignore` permitem somente os quatro novos PNGs, preservando
as demais regras. Ao preparar o commit, inclua os PNGs, a regra e o codigo juntos.

## Historico dos prompts do prototipo substituido

Prompt de geracao do atlas:

```text
Create a production-ready transparent PNG SPRITE SHEET for a web animated assistant, based EXACTLY on the reference SofIA character. This is ONE atlas asset. Layout: precisely 3 equal columns and 3 equal rows, nine equal rectangular portrait cells, no gaps, no gutters, no visible grid, no text or labels. Overall canvas portrait 2:3 ratio, ideally 1536x2304 or highest available; each cell same 2:3 ratio. Each cell contains the SAME entire FULL BODY character, from top of glowing orbital ring to silver boot soles, centered horizontally with generous transparent margin. Feet planted at the exact same baseline 94% of each cell height; head at same 8% cell height in ALL frames, body size and camera identical. No props or limbs may cross a cell boundary. Render a polished realistic 3D robot woman identical to reference: same feminine silver segmented metal head, cyan blue visor and glowing orbital halo, blue eyes, neck cables, pink collared polo with the tiny ElasGPS mark preserved if legible, dark indigo jeans, silver robot arms/hands and silver ankle boots. Preserve her established anatomy, face, clothing colors and polished metal style. No chibi, no pixel art, no style change. True transparent RGBA background, clean antialiased alpha, no green, black, white or checkerboard background, no floor, no cast shadow rectangle. Animation rows in order top to bottom: ROW1 IDLE, three subtly different adjacent breathing/blinking keyframes of her reference pose holding a small cyan hologram head in her left raised palm, right arm relaxed; very slight chest lift and eyelid change, same feet. ROW2 THINKING, three adjacent keyframes: left palm holds hologram near waist, right hand index near chin, gaze studying hologram, then head tiny thoughtful tilt then eyes toward hologram; gentle minimal incremental pose changes to create a natural ping-pong loop. ROW3 ANSWERING, three adjacent keyframes: warmly smiling, left palm presenting hologram, right hand open small conversational explanatory gesture at chest, mouth closed/slightly open/closed mid speech. Within each row consecutive poses MUST be very similar so 0-1-2-1 looping looks fluid, no big movement or jumps, no camera zoom. Entire body including boots in EVERY cell. All nine avatars strictly aligned and rendered at identical scale. This is an actual sprite atlas not a contact sheet with labels.
```

Prompt de correcao da transparencia, aplicado sobre o atlas gerado:

```text
Edit this 3x3 sprite atlas to remove the entire whitish gray background and all background shadows. Preserve EVERY character, ALL 9 full-body poses, same exact 3 columns and 3 rows at exact equal positions and same canvas 1024x1536. Do not change character anatomy, outfits, face, scale, colors or poses. Do not crop. Actual RGBA alpha 0 outside the characters including between arms/legs and between ALL cells, pure fully transparent empty pixels, not semi-transparent white, not checkerboard, no haze, no floor or shadow. Only the robot bodies, clothing and cyan holograms should remain visible. Keep blue hologram glow and clean antialiased edges with transparent surrounds. Strict remove-background-only edit.
```

## Validacao local

Os testes usam um Flask isolado e respostas simuladas, sem consultar AD/n8n:

```powershell
.\venv313\Scripts\python.exe -m tests.manual.sofia_avatar_browser_test
.\venv313\Scripts\python.exe -m tests.manual.sofia_chat_browser_test
.\venv313\Scripts\python.exe -m unittest tests.unit.sofia_page_test
```

Capturas de cada estado ficam em `instance/sofia-avatar-preview/`, fora do Git.
