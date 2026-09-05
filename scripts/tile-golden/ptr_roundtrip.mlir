cuda_tile.module @m {
  entry @ptr_roundtrip(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %7 = broadcast %6 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %8 = reshape %5 : tile<i32> -> tile<1xi32>
    %9 = broadcast %8 : tile<1xi32> -> tile<128xi32>
    %10 = iota : tile<128xi32>
    %11 = addi %9, %10 : tile<128xi32>
    %12 = offset %7, %11 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %13 = ptr_to_int %12 : tile<128xptr<f64>> -> tile<128xi64>
    %14 = constant <i64: 24> : tile<128xi64>
    %15 = addi %13, %14 : tile<128xi64>
    %16 = int_to_ptr %15 : tile<128xi64> -> tile<128xptr<f64>>
    %17, %18 = load_ptr_tko weak %16 token=%0 : tile<128xptr<f64>> -> tile<128xf64>, token
    %19 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %20 = broadcast %19 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %21 = offset %20, %11 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %22 = store_ptr_tko weak %21, %17 token=%18 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
