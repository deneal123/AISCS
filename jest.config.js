const path = require('path');

// Единый источник истины по path-алиасам — craco.config.js.
// Переиспользуем сгенерированный там moduleNameMapper, чтобы jest и webpack
// не расходились (раньше здесь был устаревший набор без @shared/@app и с неверным @api).
const cracoConfig = require('./craco.config');
const aliasMapper =
  (cracoConfig.jest && cracoConfig.jest.configure && cracoConfig.jest.configure.moduleNameMapper) || {};

module.exports = {
  testEnvironment: 'jsdom',
  setupFilesAfterEnv: ['<rootDir>/tests/setup.js'],
  testMatch: [
    '<rootDir>/tests/unit/**/*.test.{js,jsx,ts,tsx}',
    '<rootDir>/tests/integration/**/*.test.{js,jsx,ts,tsx}'
  ],
  moduleNameMapper: {
    // Стили и статика — должны идти раньше alias-паттернов
    '\\.(css|less|scss|sass)$': 'identity-obj-proxy',
    '\\.(jpg|jpeg|png|gif|svg)$': '<rootDir>/tests/__mocks__/fileMock.js',
    ...aliasMapper,
  },
  transform: {
    // automatic JSX runtime — как в webpack-сборке (CRA), чтобы компоненты
    // не были обязаны импортировать React (иначе classic runtime роняет рендер
    // тех, кто его не импортит).
    '^.+\\.(js|jsx|ts|tsx)$': ['babel-jest', { presets: [['react-app', { runtime: 'automatic' }]] }],
  },
  transformIgnorePatterns: [
    'node_modules/(?!(axios|react-markdown|vfile|vfile-message|unist-.*|unified|bail|is-plain-obj|trough|remark-.*|mdast-.*|micromark.*|decode-named-character-reference|character-entities|property-information|hast-util-.*|hastscript|space-separated-tokens|comma-separated-tokens|web-namespaces|zwitch|html-void-elements|@chakra-ui)/)',
  ],
  collectCoverageFrom: [
    'src/**/*.{js,jsx,ts,tsx}',
    '!src/index.js',
    '!src/reportWebVitals.js',
    '!src/serviceWorkerRegistration.js',
  ],
  coverageDirectory: 'coverage',
  coverageReporters: ['text', 'lcov', 'html'],
  // ⚠️ ЭТО ХРАПОВИК ОТ ФАКТА, А НЕ ЦЕЛЬ. Раньше здесь стояло 70% по всем метрикам
  // при РЕАЛЬНОМ покрытии 15.35% / 8.79% / 16.55% / 8.61%. Порог не выполнялся
  // никогда и выполниться не мог — он ничего не охранял, потому что CI гонял jest
  // БЕЗ `--coverage`, и цифра просто лежала в конфиге как декларация о намерениях.
  //
  // Числа ниже — сегодняшний факт, округлённый вниз. Смысл в том, чтобы покрытие
  // не могло УПАСТЬ незамеченным: теперь CI считает его и падает при регрессе.
  // Поднимать эти значения — отдельная осознанная работа (как с
  // backend/scripts/complexity_baseline.json), а не правка «чтобы прошло».
  coverageThreshold: {
    global: {
      branches: 8,
      functions: 8,
      lines: 16,
      statements: 15,
    },
  },
};
