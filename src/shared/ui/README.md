# Где живут общие компоненты

`src/shared/ui` — это **шелл приложения**: лэйауты, шапка, футер, ErrorBoundary.
Его подключает только слой `app`/роутер.

**Фичам импортировать отсюда нельзя.** ESLint запрещает пути с сегментом `ui`
(`**/ui/**`, `@ui/*`), поэтому переиспользуемые компоненты для фич живут рядом,
но вне `ui`:

| Куда класть | Что там |
| --- | --- |
| `shared/marketing` | секции и примитивы лендинга/платформы (`PageShell`, `Section`, `SectionHeading`, `FeatureRow`, `AgentOrbit`) |
| `shared/controls` | интерактивные контролы (`SegmentedControl`, `MagneticButton`) |
| `shared/brand` | бренд-элементы (`Eyebrow`, `TagPill`) |
| `shared/motion` | анимации появления (`Reveal`) |
| `shared/feedback` | состояния (`Skeleton`, `StateCard`) |

Кросс-фичевое переиспользование — только через публичный API фичи
(`features/<feature>/index.js`), и в этот баррель не кладут страницы: иначе
импорт одного виджета тянет за собой всю страницу с её зависимостями.

## Стилизация — только токенами

Сырые цвета (`#fff`, `rgba(...)`) и литеральные размеры в компонентах запрещены.

```jsx
import { Box } from '@chakra-ui/react';
import { colors, borderRadius } from '@theme/tokens';
import { GLASS_SURFACE } from '@theme/glass';

<Box {...GLASS_SURFACE} borderRadius={borderRadius.md} color={colors.fg[2]} />
```

Роли текста — из темы (`textStyle="title"`, `MICRO_LABEL_SX`), а не инлайновым
`fontSize`/`letterSpacing`.
