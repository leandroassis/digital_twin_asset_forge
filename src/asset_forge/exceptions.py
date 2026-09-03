"""Exception hierarchy for the asset_forge package.

One root exception per package, one subclass per distinct failure mode raised
at a wrapped external-library boundary (ifcopenshell, BaSyx, pydexpi).
"""


class AssetForgeError(Exception):
    """Base exception for all errors raised by this package."""


class ModelLoadError(AssetForgeError):
    """Raised when opening/parsing a source IFC file fails."""


class ModelNotLoadedError(AssetForgeError):
    """Raised when an operation is attempted before a model has been loaded."""


class PipelineExecutionError(AssetForgeError):
    """Raised when a Stage raises while a PlantPipeline run is in progress."""


class FederationError(AssetForgeError):
    """Raised when multiple source IFC files for one project cannot be federated."""


class DexpiUnavailableError(AssetForgeError):
    """Raised when DEXPI export is requested but the source IFC carries no
    native connectivity relations to build a topology from."""


class BasyxUploadError(AssetForgeError):
    """Raised when uploading a package or registering descriptors to BaSyx fails."""
