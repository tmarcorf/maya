# Sonic Orb

Orb animado que reage ao som, em Electron + Three.js. O visual segue a referência
em `Captura de tela 2026-08-20 154349.png`: filamentos finos de meridiano sobre um
núcleo escuro, silhueta serrilhada por ruído, coroa vermelha incandescente no polo
norte e azul-ciano no polo sul.

![referência](./Captura%20de%20tela%202026-08-20%20154349.png)

## Requisitos

- Node.js 20+ (testado em 24.12)
- Windows para captura de áudio do sistema (loopback). Microfone, arquivo e demo
  funcionam em qualquer plataforma.

## Instalação e execução

```bash
npm install
```

```bash
npm start
```

## Fontes de áudio

| Fonte | Atalho | Observações |
|---|---|---|
| Microfone | `1` | Cancelamento de eco, supressão de ruído e AGC desligados — eles achatariam a resposta. |
| Áudio do sistema | `2` | Loopback via `getDisplayMedia`; o processo principal responde com `{ audio: 'loopback' }` e a faixa de vídeo obrigatória é descartada no renderer. |
| Arquivo | `3` | Também aceita arrastar e soltar na janela. Toca em loop e sai pelos alto-falantes. |
| Demo | `4` | Espectro sintético — o orb se mexe sem nenhuma entrada conectada. |
| Parar | `0` | Desconecta tudo e deixa o orb em repouso. |

## Atalhos

| Tecla | Ação |
|---|---|
| `H` | Oculta/mostra o painel |
| `F` | Tela cheia |
| `S` | Salva um PNG do quadro atual na pasta Imagens (o caminho aparece no aviso) |
| `Espaço` | Pausa/retoma o arquivo (mantém a posição) |
| `R` | Reseta a câmera |

Arrastar com o mouse orbita; a roda aproxima.

## Como o visual é montado

Três camadas compartilham a mesma função de deslocamento (`orbRadius()` em
`src/shaders/noise.js`), então deformam como uma única superfície:

1. **Núcleo** (`SphereGeometry`, opaco, raio × 0.962) — oclui o hemisfério de trás
   e dá o interior quase preto. Fica de propósito abaixo do limiar do bloom.
2. **Filamentos** (`LineSegments`, blending aditivo) — 260 meridianos de polo a
   polo, mais algumas paralelas de latitude para as mechas horizontais da borda.
   O brilho é ponderado pela silhueta (`1 - |dot(normal, viewDir)|`), por isso o
   centro fica escuro e a borda queima.
3. **Flares dos polos** — dois sprites aditivos onde os meridianos convergem.

O deslocamento soma um fBm de ruído simplex com uma textura 1D do espectro
amostrada por longitude, o que faz a silhueta dançar como um equalizador radial.

Pós-processamento: `RenderPass` → `UnrealBloomPass` → grade (vinheta, aberração
cromática nas bordas, grão) → `OutputPass` com tone mapping ACES.

### Mapeamento áudio → visual

| Áudio | Efeito |
|---|---|
| Nível (RMS) | Respiração do raio, energia geral, força do bloom |
| Graves | Amplitude do ruído, flare do polo norte, raio do bloom |
| Médios | Velocidade de rotação e da evolução do ruído |
| Agudos | Detalhe de alta frequência, espinhos, flare do polo sul |
| Batida | Impulso de raio, empurrão na rotação, estouro do bloom |

O RMS é normalizado por um pico de decaimento lento, então material silencioso
continua expressivo sem estourar em material alto.

## Estrutura

```
electron/main.js       processo principal: protocolo orb://, CSP com nonce, loopback
electron/preload.js    ponte mínima (plataforma, tela cheia)
src/index.html         documento + import map do Three
src/app.js             UI, atalhos, drag & drop, medidor
src/visualizer.js      renderer, câmera, composer, paletas
src/orb.js             geometria e materiais do orb
src/audio-engine.js    grafo Web Audio, bandas, detecção de batida
src/shaders/noise.js   ruído simplex + deslocamento compartilhado
src/shaders/grade.js   passe final de grade
```

O app é servido por um esquema próprio (`orb://`) em vez de `file://`: isso dá
uma origem real, então o import map e módulos ES carregam sem erro de CORS e
`getUserMedia` vê um contexto seguro. O `index.html` é servido com um nonce novo
a cada carga, o que permite CSP estrita mesmo com o import map inline.

## Ajustes

Os sliders cobrem sensibilidade, turbulência, detalhe, velocidade, brilho e bloom.
Para mexer no visual base: densidade dos filamentos em `new Orb({ meridians, segments, rings })`
(`src/visualizer.js`), cores em `PALETTES` no mesmo arquivo, e as constantes de
amplitude em `radialOffset()` (`src/shaders/noise.js`).
