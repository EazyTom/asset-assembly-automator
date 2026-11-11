namespace AssetAssembly.Import.Runtime
{
    /// <summary>Shared display labels for AAA asset kinds.</summary>
    public static class AaaLabels
    {
        public const string Character = "AAA Character";
        public const string Vehicle = "AAA Vehicle";
        public const string Aircraft = "AAA Aircraft";

        public static string ForKind(string assetKind) => assetKind switch
        {
            "vehicle" => Vehicle,
            "aircraft" => Aircraft,
            _ => Character,
        };
    }
}
