import React, { Component } from "react";
import { Box, VStack, Text, Heading, Button, Icon } from "@chakra-ui/react";
import { WarningTwoIcon } from "@chakra-ui/icons";
import { colors, borderRadius } from "@theme/tokens";
import ActionLink from '@shared/controls/ActionLink';
import useDocumentTitle from '@shared/hooks/useDocumentTitle';

/**
 * Error Boundary для перехвата ошибок в дереве компонентов
 * Предоставляет graceful degradation при критических ошибках
 */
class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = {
      hasError: false,
    };
    // Привязка методов к this
    this.handleReset = this.handleReset.bind(this);
    this.handleReload = this.handleReload.bind(this);
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch() {
    // App-owned diagnostics never receive component stacks or exception bodies.
    this.props.onError?.({ component: 'render_boundary', code: 'internal' });
  }

  handleReset() {
    this.setState({ hasError: false });

    // Вызов callback при сбросе
    if (this.props.onReset) {
      this.props.onReset();
    }
  }

  handleReload() {
    window.location.reload();
  }

  render() {
    const { hasError } = this.state;
    const {
      children,
      fallback,
      fallbackRender,
      level = "page", // "page" | "section" | "component"
    } = this.props;

    if (hasError) {
      // Кастомный fallback через render prop
      if (fallbackRender) {
        return fallbackRender({
          error: { code: 'internal' },
          errorInfo: null,
          reset: this.handleReset,
          reload: this.handleReload,
        });
      }

      // Кастомный fallback компонент
      if (fallback) {
        return fallback;
      }

      // Дефолтный UI в зависимости от уровня
      return (
        <ErrorFallback
          level={level}
          onReset={this.handleReset}
          onReload={this.handleReload}
        />
      );
    }

    return children;
  }
}

/**
 * Fallback UI компонент
 */
function ErrorPageTitle() {
  useDocumentTitle('Ошибка страницы');
  return null;
}

export function ErrorFallback({ level = 'page', onReset, onReload, title, description }) {
  const isPage = level === "page";
  const isSection = level === "section";

  const containerStyles = {
    page: {
      minH: "60vh",
      p: 8,
    },
    section: {
      p: 6,
      borderRadius: borderRadius.xl,
      border: "1px solid",
      borderColor: colors.errorBorder,
      bg: colors.errorSoft,
    },
    component: {
      p: 4,
      borderRadius: borderRadius.lg,
      border: "1px dashed",
      borderColor: colors.errorBorder,
    },
  };

  return (
    <Box {...containerStyles[level]} role="alert" aria-live="assertive">
      {isPage && <ErrorPageTitle />}
      <VStack spacing={4} align="center" justify="center" h="full">
        <Icon as={WarningTwoIcon} boxSize={isPage ? 16 : isSection ? 12 : 8} color={colors.error} />

        <VStack spacing={2} textAlign="center">
          <Heading
            as={isPage ? 'h1' : 'h2'}
            fontSize={isPage ? "2xl" : isSection ? "xl" : "lg"}
            fontWeight="bold"
            color={colors.text.primary}
          >
            {title || (isPage ? "Не удалось открыть страницу" : "Ошибка компонента")}
          </Heading>

          <Text fontSize={isPage ? "md" : "sm"} color={colors.text.secondary} maxW="400px">
            {description || (isPage
              ? "Произошла непредвиденная ошибка. Попробуйте обновить страницу."
              : "Этот компонент временно недоступен.")}
          </Text>
        </VStack>

        <VStack spacing={2}>
          {onReset && <Button variant="primary" size={isPage ? "lg" : "md"} onClick={onReset}>
            Попробовать снова
          </Button>}

          {isPage && onReload && (
            <Button variant={onReset ? 'ghost' : 'primary'} h="44px" onClick={onReload}>
              Обновить страницу
            </Button>
          )}
          {isPage && <ActionLink href="/" variant="ghost" h="44px">На главную</ActionLink>}
        </VStack>
      </VStack>
    </Box>
  );
}

/**
 * HOC для оборачивания компонентов в Error Boundary
 */
export function withErrorBoundary(Component, errorBoundaryProps = {}) {
  const WrappedComponent = (props) => (
    <ErrorBoundary {...errorBoundaryProps}>
      <Component {...props} />
    </ErrorBoundary>
  );

  WrappedComponent.displayName = `withErrorBoundary(${Component.displayName || Component.name || "Component"})`;

  return WrappedComponent;
}

/**
 * Хук для использования с функциональными компонентами
 * Позволяет программно триггерить ошибку для тестирования
 */
export function useErrorHandler() {
  const [error, setError] = React.useState(null);

  if (error) {
    throw error;
  }

  return {
    showBoundary: (error) => setError(error),
    reset: () => setError(null),
  };
}

export default ErrorBoundary;
