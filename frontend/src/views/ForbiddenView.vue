<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'

const { t } = useI18n()
</script>

<template>
  <div class="mx-auto flex max-w-md flex-col gap-3 pt-14 text-center">
    <h1 class="text-xl font-semibold tracking-tight">{{ t('auth.forbidden.title') }}</h1>
    <p class="text-sm text-ink-2">{{ t('auth.forbidden.body') }}</p>
    <RouterLink to="/" class="btn self-center">{{ t('auth.forbidden.home') }}</RouterLink>
  </div>
</template>
