cuda_tile.module @m {
  entry @silu(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 1024> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<1024xi32>
    %8 = iota : tile<1024xi32>
    %9 = addi %7, %8 : tile<1024xi32>
    %10 = constant <i32: 1000> : tile<1024xi32>
    %11 = cmpi less_than %9, %10, signed : tile<1024xi32> -> tile<1024xi1>
    %12 = constant <f64: 0.0> : tile<1024xf64>
    %13 = constant <f64: 1.0> : tile<1024xf64>
    %14 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %15 = broadcast %14 : tile<1xptr<f64>> -> tile<1024xptr<f64>>
    %16 = offset %15, %9 : tile<1024xptr<f64>>, tile<1024xi32> -> tile<1024xptr<f64>>
    %17, %18 = load_ptr_tko weak %16, %11, %12 token=%0 : tile<1024xptr<f64>>, tile<1024xi1>, tile<1024xf64> -> tile<1024xf64>, token
    %19 = negf %17 : tile<1024xf64>
    %20 = exp %19 : tile<1024xf64>
    %21 = addf %13, %20 rounding<nearest_even> : tile<1024xf64>
    %22 = divf %17, %21 rounding<nearest_even> : tile<1024xf64>
    %23 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %24 = broadcast %23 : tile<1xptr<f64>> -> tile<1024xptr<f64>>
    %25 = offset %24, %9 : tile<1024xptr<f64>>, tile<1024xi32> -> tile<1024xptr<f64>>
    %26 = store_ptr_tko weak %25, %22, %11 token=%18 : tile<1024xptr<f64>>, tile<1024xf64>, tile<1024xi1> -> token
    return
  }
}
