cuda_tile.module @m {
  entry @interleave(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<128xi32>
    %8 = iota : tile<128xi32>
    %9 = addi %7, %8 : tile<128xi32>
    %10 = constant <i32: 500> : tile<128xi32>
    %11 = cmpi less_than %9, %10, signed : tile<128xi32> -> tile<128xi1>
    %12 = constant <f64: 0.0> : tile<128xf64>
    %13 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %14 = broadcast %13 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %15 = offset %14, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %16, %17 = load_ptr_tko weak %15, %11, %12 token=%0 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %18 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %19 = broadcast %18 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %20 = offset %19, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %21, %22 = load_ptr_tko weak %20, %11, %12 token=%17 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %23 = constant <i32: 2> : tile<i32>
    %24 = muli %5, %23 : tile<i32>
    %25 = reshape %24 : tile<i32> -> tile<1xi32>
    %26 = broadcast %25 : tile<1xi32> -> tile<128xi32>
    %27 = iota : tile<128xi32>
    %28 = constant <i32: 2> : tile<128xi32>
    %29 = muli %27, %28 : tile<128xi32>
    %30 = addi %26, %29 : tile<128xi32>
    %31 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %32 = broadcast %31 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %33 = offset %32, %30 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %34 = store_ptr_tko weak %33, %16, %11 token=%22 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    %35 = constant <i32: 1> : tile<i32>
    %36 = addi %24, %35 : tile<i32>
    %37 = reshape %36 : tile<i32> -> tile<1xi32>
    %38 = broadcast %37 : tile<1xi32> -> tile<128xi32>
    %39 = iota : tile<128xi32>
    %40 = constant <i32: 2> : tile<128xi32>
    %41 = muli %39, %40 : tile<128xi32>
    %42 = addi %38, %41 : tile<128xi32>
    %43 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %44 = broadcast %43 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %45 = offset %44, %42 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %46 = store_ptr_tko weak %45, %21, %11 token=%34 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    return
  }
}
