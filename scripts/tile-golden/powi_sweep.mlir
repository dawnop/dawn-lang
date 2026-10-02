cuda_tile.module @m {
  entry @powi_sweep(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<i32>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 256> : tile<i32>
    %7 = muli %1, %6 : tile<i32>
    %8 = reshape %5 : tile<i32> -> tile<1xi32>
    %9 = broadcast %8 : tile<1xi32> -> tile<128xi32>
    %10 = iota : tile<128xi32>
    %11 = addi %9, %10 : tile<128xi32>
    %12 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %13 = broadcast %12 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %14 = offset %13, %11 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %15, %16 = load_ptr_tko weak %14 token=%0 : tile<128xptr<f64>> -> tile<128xf64>, token
    %17 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %18 = broadcast %17 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %19 = offset %18, %11 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %20, %21 = load_ptr_tko weak %19 token=%16 : tile<128xptr<i32>> -> tile<128xi32>, token
    %22 = fpowi %15, %20 : tile<128xf64>, tile<128xi32>
    %23 = reshape %7 : tile<i32> -> tile<1xi32>
    %24 = broadcast %23 : tile<1xi32> -> tile<128xi32>
    %25 = iota : tile<128xi32>
    %26 = addi %24, %25 : tile<128xi32>
    %27 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %28 = broadcast %27 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %29 = offset %28, %26 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %30 = store_ptr_tko weak %29, %22 token=%21 : tile<128xptr<f64>>, tile<128xf64> -> token
    %31 = constant <i32: 128> : tile<i32>
    %32 = addi %7, %31 : tile<i32>
    %33 = trunci %20 : tile<128xi32> -> tile<128xi8>
    %34 = fpowi %15, %33 : tile<128xf64>, tile<128xi8>
    %35 = reshape %32 : tile<i32> -> tile<1xi32>
    %36 = broadcast %35 : tile<1xi32> -> tile<128xi32>
    %37 = iota : tile<128xi32>
    %38 = addi %36, %37 : tile<128xi32>
    %39 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %40 = broadcast %39 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %41 = offset %40, %38 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %42 = store_ptr_tko weak %41, %34 token=%30 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
