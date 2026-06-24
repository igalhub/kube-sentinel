{{/*
Fully qualified app name. Avoids duplicating the chart name when the release
name already contains it (e.g. release=kube-sentinel, chart=kube-sentinel).
*/}}
{{- define "kube-sentinel.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
