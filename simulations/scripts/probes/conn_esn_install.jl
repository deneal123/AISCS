import Pkg
specs = [
    # Compatibility repair after the captured baseline: NonlinearSolve 3.14.0
    # imports termination modes removed from the resolved DiffEqBase 6.174.0.
    # 6.155.0 still exports them and satisfies OrdinaryDiffEq 6.89.0 >=6.154.
    # This is our environment pin, not a supplied author Manifest.
    Pkg.PackageSpec(name="DiffEqBase", version="6.155.0"),
    # The v6.89.0 umbrella source contains SymplecticRK 1.1.0. The resolver
    # selected 1.2.0, whose default_linear_interpolation import is absent from
    # the compatible resolved Core 1.6.0; keep the captured failure separately.
    Pkg.PackageSpec(name="OrdinaryDiffEqSymplecticRK", version="1.1.0"),
    Pkg.PackageSpec(name="Distributions", version="0.25.113"),
    Pkg.PackageSpec(name="StatsBase", version="0.34.3"),
    Pkg.PackageSpec(name="OrdinaryDiffEq", version="6.89.0"),
    Pkg.PackageSpec(name="Graphs", version="1.9.0"),
    Pkg.PackageSpec(name="LightGraphs", version="1.3.5"),
    Pkg.PackageSpec(name="GraphRecipes", version="0.5.13"),
    Pkg.PackageSpec(name="HypothesisTests", version="0.11.3"),
    Pkg.PackageSpec(name="FFTW", version="1.8.0"),
    Pkg.PackageSpec(name="CSV", version="0.10.15"),
    Pkg.PackageSpec(name="DataFrames", version="1.7.0"),
]
append!(specs, [Pkg.PackageSpec(name=name) for name in ["Plots", "Arrow", "FileIO", "Interpolations", "ProgressLogging", "GraphPlot", "SimpleGraphs", "SimpleWeightedGraphs", "NetworkLayout", "JLD2", "JSON"]])
try
    Pkg.add(specs)
finally
    if isfile("Project.toml")
        cp("Project.toml", "/work/dependencies.project.toml", force=true)
    end
    if isfile("Manifest.toml")
        cp("Manifest.toml", "/work/dependencies.lock.toml", force=true)
    end
end
Pkg.status(mode=Pkg.PKGMODE_MANIFEST)
