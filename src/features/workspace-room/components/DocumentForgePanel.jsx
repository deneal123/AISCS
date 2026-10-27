import {
  Badge,
  Box,
  Button,
  HStack,
  Input,
  Spinner,
  Text,
  VStack,
} from '@chakra-ui/react';
import { FiEye, FiFileText, FiRefreshCw, FiX } from '@shared/icons';
import AppSelect from '@shared/controls/AppSelect';
import { borderRadius, colors } from '@theme/tokens';
import { DocumentAuthoringPanel } from './DocumentAuthoringPanel';

const BUILD_LABELS = {
  queued: 'В очереди',
  preparing: 'Подготовка',
  building: 'Сборка',
  deterministic_audit: 'Техническая проверка',
  visual_pending: 'Ожидает визуальной проверки',
  visual_audit: 'Визуальная проверка',
  publishing: 'Публикация',
  preview_ready: 'Черновик готов',
  ready: 'Готово',
  failed: 'Не собрано',
  cancelled: 'Отменено',
};

const DIAGNOSTIC_LABELS = {
  undefined_reference: 'Есть неопределённые ссылки',
  undefined_citation: 'Есть неопределённые цитирования',
  multiply_defined: 'Обнаружены повторные определения',
  overfull_box: 'Часть содержимого выходит за область набора',
  underfull_box: 'Есть разреженные строки или блоки',
  compile_failed: 'LaTeX не удалось собрать',
  unsupported_character: 'Шрифт или кодировка не поддерживает символ. Проверьте язык документа',
  pdf_invalid: 'Структура PDF повреждена',
  type3_font: 'Использован недопустимый шрифт Type 3',
  page_limit: 'Превышен лимит страниц профиля',
  page_geometry: 'Размер страницы не соответствует профилю',
  page_orientation: 'Ориентация страницы не соответствует профилю',
  bibliography_missing: 'Для этого профиля обязательна библиография',
  anonymization_failed: 'Анонимизация не прошла проверку',
  required_section: 'Отсутствует обязательный раздел',
  unresolved_placeholder: 'Остались незаполненные обязательные поля',
  visual_audit_unavailable: 'Визуальная проверка моделью не выполнялась',
  visual_blank_page: 'Обнаружена пустая страница',
  visual_clipping: 'Часть содержимого обрезана',
  visual_overlap: 'Элементы перекрывают друг друга',
  visual_readability: 'Есть проблемы с читаемостью',
  visual_table_overflow: 'Таблица выходит за границы страницы',
  visual_image_quality: 'Качество изображения недостаточно',
  visual_header_footer: 'Колонтитулы оформлены некорректно',
  visual_composition: 'Композиция страницы требует исправления',
  preview_unavailable: 'Предпросмотр недоступен',
  documentclass_mismatch: 'Класс документа не соответствует выбранному профилю',
  vendor_license_missing: 'Для публикации исходников не указана лицензия vendor-пакета',
  authoring_invalid: 'Структура документа повреждена или не соответствует сохранённой версии',
  citation_unknown: 'Ссылка указывает на источник, которого нет в реестре исследования',
  evidence_required: 'Для финала нужны проверяемые источники и ссылки на них',
};

const FAILURE_LABELS = {
  source_changed: 'Исходники изменились во время сборки. Запустите проверку ещё раз.',
  build_timeout: 'Сборка превысила допустимое время.',
  build_cancelled: 'Сборка отменена.',
  compile_failed: 'LaTeX не удалось собрать.',
  audit_failed: 'PDF собран, но не прошёл обязательную проверку.',
  visual_audit_failed: 'PDF не прошёл обязательную визуальную проверку.',
  visual_unavailable: 'Визуальная проверка временно недоступна. Её можно повторить.',
  visual_interrupted: 'Проверка была прервана перезапуском и может быть продолжена.',
  build_interrupted: 'Сборка была прервана перезапуском. Запустите её ещё раз.',
  artifact_too_large: 'Результат превышает допустимый размер.',
  runtime_unavailable: 'Среда сборки временно недоступна.',
  invalid_project: 'Структура проекта повреждена или неполна.',
  profile_mismatch: 'Настройки проекта не соответствуют профилю.',
  evidence_required: 'Черновик сохранён, но финал требует проверяемых источников.',
  unresolved_requirements: 'Черновик сохранён, но обязательные реквизиты ещё не заполнены.',
  authoring_unsupported: 'Черновик сохранён, но этот формат нельзя собрать автоматически.',
  vendor_profile_invalid: 'Формат издателя не прошёл изолированную пробную сборку.',
};

const PUBLICATION_LABELS = {
  pending_audit: 'Ожидает визуальной проверки',
  pending_delivery: 'Ожидает сохранения в Библиотеку',
  delivered: 'Сохранён в Библиотеке',
  terminal: 'Финал не удалось сохранить',
};

const MODE_LABELS = {
  draft: 'Черновик',
  submission: 'Подача',
  camera_ready: 'Финальная версия',
};
const safeModeLabel = (value) => (
  Object.hasOwn(MODE_LABELS, value) ? MODE_LABELS[value] : 'Режим уточняется'
);

const safeBuildLabel = (value) => BUILD_LABELS[value] || 'Состояние обновляется';
const safeDiagnosticLabel = (value) => DIAGNOSTIC_LABELS[value] || 'Требуется проверка документа';
const safeFailureLabel = (value) => FAILURE_LABELS[value] || 'Сборка завершилась безопасной ошибкой.';

export function documentPipelineStages(build, authoring) {
  const authoringReady = authoring?.state === 'ready';
  const queued = ['queued', 'preparing'].includes(build?.state);
  const compiling = build?.state === 'building';
  const deterministic = build?.state === 'deterministic_audit';
  const audited = ['preview_ready', 'visual_pending', 'visual_audit', 'publishing', 'ready']
    .includes(build?.state);
  const compilationStatus = !build ? 'не запускалась'
    : queued ? 'ожидает запуска'
      : compiling ? 'выполняется'
        : deterministic || audited ? 'завершена' : 'состояние уточняется';
  const auditStatus = !build || queued || compiling ? 'не запускался'
    : deterministic ? 'выполняется' : audited ? 'пройден' : 'состояние уточняется';
  const visual = ['visual_pending', 'visual_audit'].includes(build?.state);
  const delivery = build?.publication_state;
  return [
    ['Авторинг', authoringReady ? 'структура готова' : 'ожидает структуры'],
    ['Сборка', compilationStatus],
    ['Технический аудит', auditStatus],
    [
      'Визуальный аудит',
      build?.state === 'visual_pending'
        ? 'проверка требуется'
        : visual
          ? 'выполняется'
          : build?.state === 'ready'
            ? 'пройден'
            : 'не запускался',
    ],
    ['Библиотека', delivery ? (PUBLICATION_LABELS[delivery] || 'состояние уточняется') : 'не отправлялся'],
  ];
}

export function PipelineStatus({ build, authoring }) {
  return (
    <VStack align="stretch" spacing={1} aria-label="Этапы подготовки документа">
      {documentPipelineStages(build, authoring).map(([name, status]) => (
        <HStack key={name} justify="space-between" align="start">
          <Text fontSize="10px" color={colors.fg[4]}>{name}</Text>
          <Text fontSize="10px" color={colors.fg[3]} textAlign="right">{status}</Text>
        </HStack>
      ))}
    </VStack>
  );
}

export function DocumentForgePanel({ document, previewVisible = true, previewActionVisible = true, section = 'all', blocked = false }) {
  const {
    profiles = [], profilesState, loadProfiles, selectedProfile, setSelectedProfile, selectedMode, setSelectedMode,
    selectedLocale, setSelectedLocale, project, build, busy, previewUrl,
    previewError, previewBusy,
    publicationError, publicationChecking, checkPublication,
    targetPath, setTargetPath,
    vendorFiles = [], selectedVendorFile, setSelectedVendorFile,
    vendorProfiles = [], selectedVendorPackage, setSelectedVendorPackage,
    vendorTargetPath, setVendorTargetPath,
    authoring, loadAuthoring,
    createProject, applyProfile, applyVendorOverlay, activateVendorProfile,
    buildProject, cancelBuild, openPreview, openDiagnostic, publish,
  } = document || {};
  const profileOptions = profiles.map((item) => ({
    value: item.profile_id,
    label: `${item.label} · ${item.paper} · ${item.orientation === 'landscape' ? 'альбомный' : 'книжный'}`,
  }));
  const isBuilding = build && [
    'queued', 'preparing', 'building', 'deterministic_audit', 'visual_audit', 'publishing',
  ].includes(build.state);
  const pdf = build?.artifacts?.find((item) => item.role === 'pdf');
  const profileChanged = Boolean(
    project?.profile?.profile_id && project.profile.profile_id !== selectedProfile,
  );
  const settingsChanged = profileChanged || project?.mode !== selectedMode || project?.locale !== selectedLocale;
  const canPreview = Boolean(
    pdf && ['preview_ready', 'visual_pending', 'visual_audit', 'ready'].includes(build?.state),
  );
  const publicationPending = ['pending_audit', 'pending_delivery'].includes(
    build?.publication_state,
  );
  const modeOptions = Object.entries(MODE_LABELS).map(([value, label]) => ({ value, label }));
  const localeOptions = [
    { value: 'ru-RU', label: 'Русский' },
    { value: 'en-US', label: 'English' },
  ];
  const vendorOptions = vendorFiles.map((item) => ({
    value: item.file_id,
    label: item.name,
  }));
  const vendorProfileOptions = vendorProfiles.map((item) => ({
    value: item.package_id,
    label: `${item.package_id} · ${item.version}`,
  }));
  const formatting = section === 'formatting';
  const creation = section === 'create';
  if (formatting && !project) return (
    <Text color={colors.fg[3]}>Сначала создайте или выберите PDF-проект. Здесь появятся настройки его оформления.</Text>
  );

  return (
    <VStack align="stretch" spacing={3} pb={4}>
      {section !== 'checks' && <>
      <Box>
        <HStack justify="space-between">
          <Text fontSize="13px" fontWeight="600" color={colors.fg[2]}>
            {formatting ? 'Параметры документа' : creation ? 'Новый PDF-проект' : 'Document Forge'}
          </Text>
          {!formatting && !creation && build?.state && <Badge colorScheme={build.state === 'ready' ? 'green' : 'gray'}>
            {safeBuildLabel(build.state)}
          </Badge>}
        </HStack>
        <Text mt={1} fontSize="11.5px" color={colors.fg[4]}>
          {formatting
            ? 'Примените выбранные настройки. Новый профиль создаёт отдельный проект.'
            : creation
              ? 'Выберите профиль и язык. Создание проекта не запускает генерацию или сборку PDF.'
              : 'Профиль фиксирует геометрию и проверки. Исходники остаются редактируемыми .tex-файлами.'}
        </Text>
      </Box>

      <HStack align="start" spacing={2}>
        <Box flex="1" minW={0}>
          <Text as="label" htmlFor="document-mode" fontSize="11px" color={colors.fg[3]}>
            Режим
          </Text>
          <AppSelect
            menuPortalTarget={formatting ? null : undefined}
            size="document"
            mt={1}
            inputId="document-mode"
            ariaLabel="Режим подготовки PDF"
            value={selectedMode}
            options={modeOptions}
            onChange={setSelectedMode}
            isDisabled={Boolean(blocked || busy || isBuilding)}
          />
        </Box>
        <Box flex="1" minW={0}>
          <Text as="label" htmlFor="document-locale" fontSize="11px" color={colors.fg[3]}>
            Язык
          </Text>
          <AppSelect
            menuPortalTarget={formatting ? null : undefined}
            size="document"
            mt={1}
            inputId="document-locale"
            ariaLabel="Язык PDF-документа"
            value={selectedLocale}
            options={localeOptions}
            onChange={setSelectedLocale}
            isDisabled={Boolean(blocked || busy || isBuilding)}
          />
        </Box>
      </HStack>

      <Box>
        <Text as="label" htmlFor="document-profile" fontSize="11px" color={colors.fg[3]}>
          Профиль документа
        </Text>
        <AppSelect
          menuPortalTarget={formatting ? null : undefined}
          size="document"
          mt={1}
          inputId="document-profile"
          ariaLabel="Профиль PDF-документа"
          value={selectedProfile}
          options={profileOptions}
          onChange={setSelectedProfile}
          isDisabled={Boolean(blocked || busy || isBuilding)}
        />
      </Box>

      {formatting && profilesState === 'unavailable' && <Box>
        <Text fontSize="xs" color={colors.warning}>Не удалось обновить список форматов.</Text>
        <Button size="document" variant="ghost" onClick={loadProfiles}>Повторить загрузку форматов</Button>
      </Box>}

      {!project ? (
        <Button
          size="document"
          variant="workbenchPrimary"
          leftIcon={<FiFileText />}
          onClick={createProject}
          isLoading={busy === 'create'}
          isDisabled={!profiles.length}
        >
          Создать проект
        </Button>
      ) : (
        <VStack align="stretch" spacing={2}>
          {!formatting && <Box p={3} borderRadius={borderRadius.md} border={`1px solid ${colors.border.subtle}`}>
            <Text fontSize="11px" color={colors.fg[4]}>Проект</Text>
            <Text mt={1} fontSize="12px" color={colors.fg[2]} noOfLines={1} title={project.path}>
              {project.path}
            </Text>
            <Text mt={1} fontSize="10.5px" color={colors.fg[4]}>
              {project.profile?.label || 'Профиль документа'} · {safeModeLabel(project.mode)}
            </Text>
          </Box>}
          {(formatting || settingsChanged) && (
            <VStack align="stretch" spacing={2}>
              {profileChanged && (
                <Box>
                  <Text as="label" htmlFor="document-target-path" fontSize="11px" color={colors.fg[3]}>
                    Новый проект
                  </Text>
                  <Input
                    id="document-target-path"
                    mt={1}
                    size="sm"
                    value={targetPath || ''}
                    onChange={(event) => setTargetPath?.(event.target.value)}
                    isDisabled={Boolean(blocked || busy || isBuilding)}
                    aria-describedby="document-target-help"
                  />
                  <Text id="document-target-help" mt={1} fontSize="10.5px" color={colors.fg[4]}>
                    Исходный проект останется без изменений.
                  </Text>
                </Box>
              )}
              <Button
                size="document"
                variant="workbenchPrimary"
                onClick={applyProfile}
                isLoading={busy === 'profile'}
                isDisabled={Boolean(!settingsChanged || blocked || busy || isBuilding || (profileChanged && !String(targetPath || '').trim()))}
              >
                {profileChanged ? 'Создать проект с профилем' : 'Применить настройки'}
              </Button>
            </VStack>
          )}
          <Box
            as={formatting ? 'details' : 'div'}
            p={formatting ? 0 : 3}
            borderRadius={borderRadius.md}
            border={formatting ? 0 : `1px solid ${colors.border.subtle}`}
          >
            <Text as={formatting ? 'summary' : 'p'} cursor={formatting ? 'pointer' : undefined}
              py={formatting ? 2 : 0} fontSize="11px" fontWeight="600" color={colors.fg[3]}>
              Шаблон издателя
            </Text>
            <Text mt={1} fontSize="10.5px" color={colors.fg[4]}>
              ZIP из Библиотеки проверяется и подключается только к этому проекту.
              Среда LaTeX и сетевые ограничения не меняются.
            </Text>
            {vendorOptions.length ? (
              <VStack mt={2} align="stretch" spacing={2}>
                <AppSelect
                  menuPortalTarget={formatting ? null : undefined}
                  size="document"
                  inputId="document-vendor-overlay"
                  ariaLabel="Vendor-пакет из Библиотеки"
                  value={selectedVendorFile}
                  options={vendorOptions}
                  onChange={setSelectedVendorFile}
                  isDisabled={Boolean(blocked || busy || isBuilding)}
                />
                <Button
                  size="document"
                  variant="workbenchSecondary"
                  onClick={applyVendorOverlay}
                  isLoading={busy === 'vendor'}
                  isDisabled={!selectedVendorFile || Boolean(blocked || busy || isBuilding)}
                >
                  Добавить в проект
                </Button>
              </VStack>
            ) : (
              <Text mt={2} fontSize="10.5px" color={colors.fg[4]}>
                Сначала загрузите ZIP с vendor.toml в Библиотеку.
              </Text>
            )}
            {project.vendor_overlays?.length > 0 && (
              <VStack mt={2} align="stretch" spacing={1} aria-label="Подключённые vendor-пакеты">
                {project.vendor_overlays.map((overlay) => (
                  <HStack key={`${overlay.package_id}:${overlay.version}`} justify="space-between">
                    <Text fontSize="10.5px" color={colors.fg[3]} noOfLines={1}>
                      {overlay.package_id}
                    </Text>
                    <Badge colorScheme="gray" fontSize="9px">
                      {overlay.version} · изолирован
                    </Badge>
                  </HStack>
                ))}
              </VStack>
            )}
            {vendorProfileOptions.length > 0 && (
              <VStack mt={3} pt={3} align="stretch" spacing={2} borderTop={`1px solid ${colors.border.subtle}`}>
                <Text fontSize="10.5px" color={colors.fg[3]}>
                  Формат vendor v2 активируется только в новом проекте после пробной сборки.
                </Text>
                <AppSelect
                  menuPortalTarget={formatting ? null : undefined}
            size="document"
                  inputId="document-vendor-profile"
                  ariaLabel="Установленный формат издателя"
                  value={selectedVendorPackage}
                  options={vendorProfileOptions}
                  onChange={setSelectedVendorPackage}
                  isDisabled={Boolean(busy || isBuilding)}
                />
                <Box>
                  <Text as="label" htmlFor="document-vendor-target" fontSize="11px" color={colors.fg[3]}>
                    Новый проект с форматом
                  </Text>
                  <Input
                    id="document-vendor-target"
                    mt={1}
                    size="sm"
                    value={vendorTargetPath || ''}
                    onChange={(event) => setVendorTargetPath?.(event.target.value)}
                    isDisabled={Boolean(busy || isBuilding)}
                    aria-describedby="document-vendor-target-help"
                  />
                  <Text id="document-vendor-target-help" mt={1} fontSize="10px" color={colors.fg[4]}>
                    Исходный проект и его профиль останутся без изменений.
                  </Text>
                </Box>
                <Button
                  size="document"
                  variant="workbenchSecondary"
                  onClick={activateVendorProfile}
                  isLoading={busy === 'vendor-profile'}
                  isDisabled={!selectedVendorPackage || !String(vendorTargetPath || '').trim() || Boolean(busy || isBuilding)}
                >
                  Создать проект с форматом
                </Button>
              </VStack>
            )}
          </Box>
          {!formatting && <><Box
            p={3}
            borderRadius={borderRadius.md}
            border={`1px solid ${colors.border.subtle}`}
          >
            <HStack mb={2} justify="space-between">
              <Text fontSize="11px" fontWeight="600" color={colors.fg[3]}>
                Структурированный документ
              </Text>
              {authoring?.state === 'unavailable' && (
                <Button size="document" variant="ghost" onClick={() => loadAuthoring?.()}>
                  Повторить
                </Button>
              )}
            </HStack>
            <DocumentAuthoringPanel authoring={authoring} onOpenSource={openDiagnostic} />
          </Box>
          <Box
            p={3}
            borderRadius={borderRadius.md}
            border={`1px solid ${colors.border.subtle}`}
          >
            <PipelineStatus build={build} authoring={authoring} />
          </Box>
          <HStack wrap="wrap" data-toast-protected-actions>
            <Button
              size="document"
              variant="workbenchSecondary"
              leftIcon={<FiRefreshCw />}
              onClick={() => buildProject(false)}
              isLoading={busy === 'build'}
              isDisabled={Boolean(busy || isBuilding)}
            >
              Собрать черновик
            </Button>
            <Button
              size="document"
              variant="workbenchPrimary"
              onClick={() => buildProject(true)}
              isLoading={busy === 'final'}
              isDisabled={Boolean(busy || isBuilding)}
            >
              Проверить финал
            </Button>
            {isBuilding && (
              <Button size="document" variant="ghost" leftIcon={<FiX />} onClick={cancelBuild}>
                Отменить
              </Button>
            )}
          </HStack></>}
        </VStack>
      )}

      </>}
      {['all', 'checks'].includes(section) && <>
      {section === 'checks' && <PipelineStatus build={build} authoring={authoring} />}
      {isBuilding && (
        <HStack role="status" aria-live="polite" color={colors.fg[3]}>
          <Spinner size="xs" />
          <Text fontSize="11.5px">{safeBuildLabel(build.state)}… редактор остаётся доступен.</Text>
        </HStack>
      )}

      {build?.state === 'failed' && (
        <Box
          role="alert"
          p={3}
          borderRadius={borderRadius.md}
          border={`1px solid ${colors.warningBorder}`}
          bg={colors.warningSoft}
        >
          <Text fontSize="11.5px" color={colors.fg[3]}>
            {safeFailureLabel(build.failure_code)}
          </Text>
        </Box>
      )}

      {build?.state === 'visual_pending' && (
        <Box
          role="status"
          p={3}
          borderRadius={borderRadius.md}
          border={`1px solid ${colors.border.subtle}`}
        >
          <Text fontSize="11.5px" color={colors.fg[3]}>
            PDF собран. Перед публикацией нужна обязательная визуальная проверка всех страниц.
          </Text>
        </Box>
      )}

      {build?.diagnostics?.length > 0 && (
        <VStack align="stretch" spacing={1}>
          <Text fontSize="11px" color={colors.fg[3]}>Диагностика</Text>
          {build.diagnostics.map((item, index) => (
            <Button
              key={`${item.code}-${item.path || ''}-${item.line || index}`}
              variant="ghost"
              justifyContent="flex-start"
              h="auto"
              minH={{ base: '44px', md: '24px' }}
              px={1}
              py={1}
              fontSize="11px"
              color={item.severity === 'error' ? colors.error : colors.fg[4]}
              whiteSpace="normal"
              textAlign="left"
              isDisabled={!item.path}
              onClick={() => openDiagnostic?.(item)}
            >
              {safeDiagnosticLabel(item.code)}
              {item.path ? ` · ${item.path}${item.line ? `:${item.line}` : ''}` : ''}
            </Button>
          ))}
        </VStack>
      )}

      {canPreview && (
        <HStack wrap="wrap" data-toast-protected-actions>
          {previewActionVisible && <Button
            size="document"
            variant="workbenchSecondary"
            leftIcon={<FiEye />}
            onClick={openPreview}
            isLoading={previewBusy}
          >
            Открыть PDF
          </Button>}
          {build?.final && ['visual_pending', 'ready'].includes(build?.state) && (
            <Button
              size="document"
              variant="workbenchPrimary"
              onClick={publish}
              isLoading={busy === 'publish'}
              isDisabled={Boolean(busy || publicationPending || publicationError
                || publicationChecking || !Object.hasOwn(build, 'publication_state')
                || ['delivered', 'terminal'].includes(build.publication_state))}
            >
              {build.state === 'visual_pending' ? 'Проверить и сохранить' : 'Сохранить в Библиотеку'}
            </Button>
          )}
        </HStack>
      )}

      {(publicationError || publicationChecking || build?.publication_state === 'terminal') && (
        <VStack
          align="stretch"
          spacing={2}
          p={3}
          borderRadius={borderRadius.md}
          border={`1px solid ${colors.border.subtle}`}
          aria-label="Состояние сохранения документа"
        >
          <Text role="status" aria-live="polite" fontSize="12px" color={colors.fg[3]}>
            {build?.publication_state === 'terminal'
              ? 'Финал не удалось сохранить в Библиотеку. Откройте Библиотеку в левой панели.'
              : publicationError
                ? 'Не удалось уточнить сохранение. Оно могло завершиться; проверьте статус перед повтором.'
                : 'Проверяю сохранение в Библиотеку. Редактор остаётся доступен.'}
          </Text>
          {build?.publication_state !== 'terminal' && (
            <Button
              size="document"
              variant="workbenchSecondary"
              alignSelf="start"
              aria-label="Проверить сохранение"
              data-toast-protected-actions
              onClick={checkPublication}
              isLoading={publicationChecking}
            >
              Проверить сохранение
            </Button>
          )}
        </VStack>
      )}

      {previewActionVisible && previewError && (
        <Text role="alert" fontSize="12px" color={colors.fg[3]}>
          Не удалось открыть PDF. Повторите открытие; исходники и готовый файл сохранены.
        </Text>
      )}

      {previewVisible && previewUrl && (
        <Box
          as="iframe"
          title="Предпросмотр PDF"
          src={previewUrl}
          w="100%"
          h="420px"
          border={`1px solid ${colors.border.subtle}`}
          borderRadius={borderRadius.md}
          bg={colors.bg.input}
        />
      )}
      </>}
    </VStack>
  );
}

export { safeBuildLabel, safeDiagnosticLabel, safeModeLabel };
