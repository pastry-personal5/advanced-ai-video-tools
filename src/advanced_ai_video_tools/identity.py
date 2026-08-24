"""Canonical application identity shared by runtime and packaging adapters."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ApplicationIdentity:
    """User-visible and compatibility names owned by the application."""

    display_name: str
    organization_name: str
    primary_command: str
    legacy_command: str
    distribution_name: str
    import_package_name: str
    bundle_identifier: str
    log_filename: str
    output_prefix: str
    workspace_marker: str
    gui_lock_filename: str


IDENTITY = ApplicationIdentity(
    display_name="Advanced AI Video Tools",
    organization_name="Advanced AI Video Tools",
    primary_command="advanced-ai-video-tools",
    legacy_command="ai-video-tools",
    distribution_name="advanced-ai-video-tools",
    import_package_name="advanced_ai_video_tools",
    bundle_identifier="com.pastrypersonal5.advancedaivideotools",
    log_filename="advanced-ai-video-tools.log",
    output_prefix="ai-",
    workspace_marker=".ai-video-tools-owned",
    gui_lock_filename="advanced-ai-video-tools-gui.lock",
)
