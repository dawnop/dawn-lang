cuda_tile.module @m {
  entry @rgb_gray(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<128xi32>
    %8 = iota : tile<128xi32>
    %9 = addi %7, %8 : tile<128xi32>
    %10 = constant <i32: 1000> : tile<128xi32>
    %11 = cmpi less_than %9, %10, signed : tile<128xi32> -> tile<128xi1>
    %12 = constant <f64: 0.0> : tile<128xf64>
    %13 = constant <i32: 3> : tile<i32>
    %14 = muli %5, %13 : tile<i32>
    %15 = reshape %14 : tile<i32> -> tile<1xi32>
    %16 = broadcast %15 : tile<1xi32> -> tile<128xi32>
    %17 = iota : tile<128xi32>
    %18 = constant <i32: 3> : tile<128xi32>
    %19 = muli %17, %18 : tile<128xi32>
    %20 = addi %16, %19 : tile<128xi32>
    %21 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %22 = broadcast %21 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %23 = offset %22, %20 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %24, %25 = load_ptr_tko weak %23, %11, %12 token=%0 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %26 = constant <i32: 1> : tile<i32>
    %27 = addi %14, %26 : tile<i32>
    %28 = reshape %27 : tile<i32> -> tile<1xi32>
    %29 = broadcast %28 : tile<1xi32> -> tile<128xi32>
    %30 = iota : tile<128xi32>
    %31 = constant <i32: 3> : tile<128xi32>
    %32 = muli %30, %31 : tile<128xi32>
    %33 = addi %29, %32 : tile<128xi32>
    %34 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %35 = broadcast %34 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %36 = offset %35, %33 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %37, %38 = load_ptr_tko weak %36, %11, %12 token=%25 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %39 = constant <i32: 2> : tile<i32>
    %40 = addi %14, %39 : tile<i32>
    %41 = reshape %40 : tile<i32> -> tile<1xi32>
    %42 = broadcast %41 : tile<1xi32> -> tile<128xi32>
    %43 = iota : tile<128xi32>
    %44 = constant <i32: 3> : tile<128xi32>
    %45 = muli %43, %44 : tile<128xi32>
    %46 = addi %42, %45 : tile<128xi32>
    %47 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %48 = broadcast %47 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %49 = offset %48, %46 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %50, %51 = load_ptr_tko weak %49, %11, %12 token=%38 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %52 = constant <f64: 0.299> : tile<128xf64>
    %53 = mulf %24, %52 rounding<nearest_even> : tile<128xf64>
    %54 = constant <f64: 0.587> : tile<128xf64>
    %55 = mulf %37, %54 rounding<nearest_even> : tile<128xf64>
    %56 = addf %53, %55 rounding<nearest_even> : tile<128xf64>
    %57 = constant <f64: 0.114> : tile<128xf64>
    %58 = mulf %50, %57 rounding<nearest_even> : tile<128xf64>
    %59 = addf %56, %58 rounding<nearest_even> : tile<128xf64>
    %60 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %61 = broadcast %60 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %62 = offset %61, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %63 = store_ptr_tko weak %62, %59, %11 token=%51 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    return
  }
}
