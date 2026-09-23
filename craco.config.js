const path = require("path");

// Единый источник версии — frontend/package.json. Пробрасываем в сборку как
// REACT_APP_VERSION (CRA инжектит любые REACT_APP_* в бандл). Выставляем здесь, в
// module-scope craco-конфига — он грузится ДО того, как react-scripts вычислит
// client-env, поэтому переменная попадёт в билд и dev-сервер без DefinePlugin.
// Больше никакого хардкода "1.0.0" — версия подтягивается сама.
process.env.REACT_APP_VERSION =
  process.env.REACT_APP_VERSION || require("./package.json").version;

const resolveSrc = (segment = "") => path.join(__dirname, "src", segment);

const alias = {
  "@": resolveSrc(""),
  "@features": resolveSrc("features"),
  "@pages": resolveSrc("pages"),
  "@utils": resolveSrc("utils"),
  "@theme": resolveSrc("theme"),
  "@app": resolveSrc("app"),
  "@shared": resolveSrc("shared"),
  "@constants": resolveSrc("constants"),
  "@api": resolveSrc("shared/api"),
  "@hooks": resolveSrc("hooks"),
};

const moduleNameMapper = Object.entries(alias).reduce((mapper, [key, target]) => {
  const escapedKey = key.replace(/[-/\\^$*+?.()|[\]{}]/g, "\\$&");
  mapper[`^${escapedKey}/(.*)$`] = `${target}/$1`;
  mapper[`^${escapedKey}$`] = target;
  return mapper;
}, {});

module.exports = {
  webpack: {
    alias,
    configure: (webpackConfig, { env }) => {
      // Оптимизация только для production
      if (env === "production") {
        // Разделение бандла на чанки для лучшего кеширования
        webpackConfig.optimization.splitChunks = {
          chunks: "all",
          minSize: 20000,
          maxSize: 244000,
          cacheGroups: {
            // Основные вендоры. ФИКСИРОВАННОГО `name` тут быть не должно: с ним
            // webpack сливает node_modules из ВСЕХ чанков (включая ленивые роуты)
            // в один общий чанк, а тот нужен entry — значит становится initial.
            // Из-за этого katex/react-markdown/refractor из ленивого /chat
            // качались на лендинге: eager-граф весил 675 КБ gzip вместо 288 КБ.
            // Без `name` webpack именует группы сам и async-only вендоры остаются
            // async.
            vendor: {
              test: /[\\/]node_modules[\\/]/,
              chunks: "all",
              priority: 10,
            },
            // Chakra UI. БЕЗ фиксированного `name` — по той же причине, что и у
            // vendor выше: с ним webpack сливал Chakra из ВСЕХ чанков (включая
            // ленивые /chat и /admin — Menu/Modal/Drawer/Table) в один общий чанк,
            // а он нужен entry → становился initial. Лендинг качал Chakra-код,
            // который используется только в чате. Без `name` webpack именует группы
            // сам, и Chakra, нужная только ленивым роутам, остаётся async.
            chakra: {
              test: /[\\/]node_modules[\\/](@chakra-ui|@emotion|framer-motion)[\\/]/,
              chunks: "all",
              priority: 20,
            },
            // Графики и визуализация в отдельный чанк
            charts: {
              test: /[\\/]node_modules[\\/](recharts|d3)[\\/]/,
              name: "charts",
              chunks: "all",
              priority: 20,
            },
            // three.js — ТОЛЬКО async-чанк (грузится лишь на лендинге при WebGL,
            // не должен попадать в eager-бандл / first paint).
            three: {
              test: /[\\/]node_modules[\\/]three[\\/]/,
              name: "three",
              chunks: "async",
              priority: 25,
            },
            // React в отдельный чанк
            react: {
              test: /[\\/]node_modules[\\/](react|react-dom|react-router|react-router-dom)[\\/]/,
              name: "react",
              chunks: "all",
              priority: 30,
            },
          },
        };

        // Включаем tree shaking
        webpackConfig.optimization.usedExports = true;
        webpackConfig.optimization.sideEffects = true;

        // Настройка Terser для агрессивной минификации
        const TerserPlugin = require("terser-webpack-plugin");
        webpackConfig.optimization.minimizer = [
          new TerserPlugin({
            terserOptions: {
              parse: {
                ecma: 8,
              },
              compress: {
                ecma: 5,
                warnings: false,
                comparisons: false,
                inline: 2,
                drop_console: true,        // Удаляем console.log
                drop_debugger: true,       // Удаляем debugger
                pure_funcs: ["console.info", "console.debug", "console.warn"],
              },
              mangle: {
                safari10: true,
              },
              output: {
                ecma: 5,
                comments: false,           // Удаляем комментарии
                ascii_only: true,
              },
            },
            extractComments: false,
          }),
        ];
      }

      return webpackConfig;
    },
  },

  devServer: (devServerConfig) => {
    // DEV-ONLY: разрешаем доступ к dev-серверу по любому Host. Нужно для
    // визуальной проверки через MCP-браузер из контейнера (host.docker.internal
    // иначе отбивается WDS host-check → «Invalid Host header»). На прод-сборку
    // (craco build) не влияет.
    devServerConfig.allowedHosts = "all";
    return devServerConfig;
  },

  eslint: {
    configure: {
      rules: {
        "import/no-restricted-paths": [
          "error",
          {
            zones: [
              { target: "./src/shared", from: "./src/features" },
              { target: "./src/shared", from: "./src/app" }
            ]
          }
        ]
      }
    }
  },
  jest: {
    configure: {
      moduleNameMapper,
    },
  },
};
