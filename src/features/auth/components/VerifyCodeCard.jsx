import React, { useCallback, useEffect, useRef, useState } from "react";
import { Button, HStack, Icon, Link, PinInput, PinInputField, Text, VStack } from "@chakra-ui/react";
import { FaCheckCircle, FaRegClipboard } from "@shared/icons";
import { resendEmailCode, verifyEmailCode } from "@api";
import { INPUT_BASE } from "@theme/glass";
import { colors } from "@theme/tokens";
import { Reveal } from "@shared/motion/Reveal";
import { useAppToast } from "@shared/hooks/useAppToast";
import { AUTH_VERIFY } from "@/content/auth";
import extractErrorInfo from "@utils/errorHandler";
import AuthFormCard from "./AuthFormCard";
import AuthPageHeader from "./AuthPageHeader";
import AuthPageShell from "./AuthPageShell";
import FormErrorBanner from "./FormErrorBanner";
import { AUTH_PRIMARY_BUTTON_SX } from "./authButtonStyles";
import { AUTH_THEME } from "../constants";

const CODE_LENGTH = 6;
const RESEND_COOLDOWN_SEC = 60;

/**
 * VerifyCodeCard — шаг ввода 6-значного кода подтверждения (регистрация / OTP при
 * входе). Композиция и стиль как у Signup/LoginWidget. `onVerified` вызывается
 * после успешного verify (сессия-cookie уже выставлена бэкендом).
 *
 * @param {string} email  куда отправлен код
 * @param {() => (void|Promise<void>)} onVerified  колбэк после успешной проверки
 * @param {() => void} [onBack]  вернуться к форме (сменить email/пароль)
 */
export default function VerifyCodeCard({ email, onVerified, onBack }) {
  const toast = useAppToast();
  const errorRef = useRef(null);
  const [code, setCode] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [cooldown, setCooldown] = useState(RESEND_COOLDOWN_SEC);

  // Обратный отсчёт до повторной отправки (код уже отправлен на предыдущем шаге).
  useEffect(() => {
    if (cooldown <= 0) return undefined;
    const timer = setInterval(() => setCooldown((s) => (s <= 1 ? 0 : s - 1)), 1000);
    return () => clearInterval(timer);
  }, [cooldown]);

  // Фокус на алерт после ошибки (a11y).
  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  const submitCode = useCallback(
    async (value) => {
      if (isLoading) return;
      setError(null);
      if (!value || value.length < CODE_LENGTH) return;
      setIsLoading(true);
      try {
        await verifyEmailCode({ email, code: value });
        await onVerified?.();
      } catch (err) {
        const { userMessage } = extractErrorInfo(err, { fallbackMessage: AUTH_VERIFY.errorFallback });
        setError(userMessage);
        setCode("");
      } finally {
        setIsLoading(false);
      }
    },
    [email, isLoading, onVerified],
  );

  const handleSubmit = (event) => {
    event.preventDefault();
    submitCode(code);
  };

  // «Вставить код»: письмо с кодом нельзя снабдить JS-кнопкой копирования, поэтому
  // удобство живёт здесь — читаем буфер обмена, оставляем только цифры, заполняем PIN.
  const [canPaste, setCanPaste] = useState(false);
  useEffect(() => {
    setCanPaste(typeof navigator !== "undefined" && !!navigator.clipboard?.readText);
  }, []);
  // Единая заливка кода из произвольного текста (только цифры) + авто-сабмит.
  const fillFromText = (text) => {
    const digits = (String(text || "").match(/\d/g) || []).join("").slice(0, CODE_LENGTH);
    if (!digits) return false;
    setError(null);
    setCode(digits);
    if (digits.length === CODE_LENGTH) submitCode(digits);
    return true;
  };
  const handlePasteCode = async () => {
    try {
      fillFromText(await navigator.clipboard.readText());
    } catch {
      // Доступ к буферу запрещён/недоступен — пользователь введёт код вручную.
    }
  };
  // Ctrl+V в любое из PIN-полей: нативный paste у PinInput не всегда распределяет
  // код по ячейкам (юзер жаловался — работала только кнопка). Перехватываем на
  // контейнере: вынимаем цифры из буфера события и заполняем сами.
  const handlePasteEvent = (e) => {
    const text = e.clipboardData?.getData("text");
    if (fillFromText(text)) e.preventDefault();
  };

  const handleResend = async () => {
    if (cooldown > 0) return;
    setError(null);
    try {
      await resendEmailCode({ email });
      setCooldown(RESEND_COOLDOWN_SEC);
      setCode("");
      toast({ status: "success", title: AUTH_VERIFY.resent });
    } catch (err) {
      const { userMessage } = extractErrorInfo(err, { fallbackMessage: AUTH_VERIFY.errorFallback });
      setError(userMessage);
    }
  };

  return (
    <AuthPageShell>
      <AuthFormCard as="form" onSubmit={handleSubmit} maxW="100%">
        <Reveal as={VStack} variant="soft" className="stagger-children" w="full" align="stretch" spacing={5}>
          <AuthPageHeader
            title={AUTH_VERIFY.title}
            description={`${AUTH_VERIFY.descriptionPrefix} ${email}`}
          />

          {error && (
            <FormErrorBanner ref={errorRef} title={AUTH_VERIFY.errorTitle} message={error} />
          )}

          <HStack spacing={2.5} justify="center" w="full" onPaste={handlePasteEvent}>
            <PinInput
              otp
              autoFocus
              placeholder=""
              value={code}
              onChange={setCode}
              onComplete={submitCode}
              isDisabled={isLoading}
            >
              {Array.from({ length: CODE_LENGTH }).map((_, i) => (
                <PinInputField
                  key={i}
                  // Без явного label Chakra подставляет английское «Please enter your
                  // pin code» — в русском интерфейсе незрячий слышал бы англ. фразу,
                  // причём одинаковую для всех шести полей. Даём русский с позицией.
                  aria-label={`Код из письма: цифра ${i + 1} из ${CODE_LENGTH}`}
                  {...INPUT_BASE}
                  h="54px"
                  w="100%"
                  maxW="52px"
                  fontSize="20px"
                  fontWeight="700"
                  textAlign="center"
                  color="white"
                />
              ))}
            </PinInput>
          </HStack>

          {canPaste && (
            <HStack justify="center">
              <Button
                type="button"
                onClick={handlePasteCode}
                variant="ghost"
                size="sm"
                leftIcon={<Icon as={FaRegClipboard} boxSize="12px" />}
                color={AUTH_THEME.accent}
                fontWeight="500"
                _hover={{ color: AUTH_THEME.accentHover, bg: "rgba(45,91,255,0.08)" }}
              >
                {AUTH_VERIFY.paste}
              </Button>
            </HStack>
          )}

          <Text fontSize="12px" color={colors.fg[4]} textAlign="center" lineHeight="1.5">
            {AUTH_VERIFY.hint}
          </Text>

          <Button
            type="submit"
            w="full"
            isLoading={isLoading}
            isDisabled={code.length < CODE_LENGTH}
            leftIcon={<Icon as={FaCheckCircle} />}
            {...AUTH_PRIMARY_BUTTON_SX}
          >
            {isLoading ? AUTH_VERIFY.submitLoading : AUTH_VERIFY.submit}
          </Button>

          <HStack spacing={1} justify="center" fontSize="sm">
            {cooldown > 0 ? (
              <Text color={AUTH_THEME.mutedText}>
                {AUTH_VERIFY.resendCountdownPrefix} {cooldown} с
              </Text>
            ) : (
              <Link
                as="button"
                type="button"
                onClick={handleResend}
                color={AUTH_THEME.accent}
                fontWeight="500"
                _hover={{ color: AUTH_THEME.accentHover, textDecoration: "none" }}
              >
                {AUTH_VERIFY.resend}
              </Link>
            )}
          </HStack>

          {onBack && (
            <HStack justify="center">
              <Link
                as="button"
                type="button"
                onClick={onBack}
                fontSize="13px"
                color={AUTH_THEME.mutedText}
                _hover={{ color: "white", textDecoration: "none" }}
              >
                {AUTH_VERIFY.changeEmail}
              </Link>
            </HStack>
          )}
        </Reveal>
      </AuthFormCard>
    </AuthPageShell>
  );
}
