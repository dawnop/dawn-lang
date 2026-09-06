cuda_tile.module @m {
  entry @view_tensor_shape(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = constant <i32: 1> : tile<i32>
    %3 = constant <i32: 0> : tile<i32>
    %4 = offset %arg0, %3 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %5, %6 = load_ptr_tko weak %4 token=%0 : tile<ptr<i32>> -> tile<i32>, token
    %7 = constant <i32: 1> : tile<i32>
    %8 = offset %arg0, %7 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %9, %10 = load_ptr_tko weak %8 token=%6 : tile<ptr<i32>> -> tile<i32>, token
    %11 = constant <i32: 2> : tile<i32>
    %12 = offset %arg0, %11 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %13, %14 = load_ptr_tko weak %12 token=%10 : tile<ptr<i32>> -> tile<i32>, token
    %15 = offset %arg1, %1 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %16 = make_tensor_view %15, shape = [%5, %9], strides = [%9, %13] : tile<i32> -> tensor_view<?x?xf64, strides=[?, ?]>
    %17, %18 = get_tensor_shape %16 : tensor_view<?x?xf64, strides=[?, ?]> -> tile<i32>
    %19, %20 = get_tensor_shape %16 : tensor_view<?x?xf64, strides=[?, ?]> -> tile<i32>
    %21, %22, %23 = get_tile_block_id : tile<i32>
    %24 = constant <i32: 32> : tile<i32>
    %25 = muli %21, %24 : tile<i32>
    %26 = reshape %25 : tile<i32> -> tile<1xi32>
    %27 = broadcast %26 : tile<1xi32> -> tile<32xi32>
    %28 = iota : tile<32xi32>
    %29 = addi %27, %28 : tile<32xi32>
    %30 = reshape %20 : tile<i32> -> tile<1xi32>
    %31 = broadcast %30 : tile<1xi32> -> tile<32xi32>
    %32 = cmpi less_than %29, %31, signed : tile<32xi32> -> tile<32xi1>
    %33 = constant <f64: 0.0> : tile<32xf64>
    %34 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %35 = broadcast %34 : tile<1xptr<f64>> -> tile<32xptr<f64>>
    %36 = offset %35, %29 : tile<32xptr<f64>>, tile<32xi32> -> tile<32xptr<f64>>
    %37, %38 = load_ptr_tko weak %36, %32, %33 token=%14 : tile<32xptr<f64>>, tile<32xi1>, tile<32xf64> -> tile<32xf64>, token
    %39 = addf %37, %37 rounding<nearest_even> : tile<32xf64>
    %40 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %41 = broadcast %40 : tile<1xptr<f64>> -> tile<32xptr<f64>>
    %42 = offset %41, %29 : tile<32xptr<f64>>, tile<32xi32> -> tile<32xptr<f64>>
    %43 = store_ptr_tko weak %42, %39, %32 token=%38 : tile<32xptr<f64>>, tile<32xf64>, tile<32xi1> -> token
    %44 = reshape %17 : tile<i32> -> tile<1xi32>
    %45 = broadcast %44 : tile<1xi32> -> tile<1xi32>
    %46 = reshape %1 : tile<i32> -> tile<1xi32>
    %47 = broadcast %46 : tile<1xi32> -> tile<1xi32>
    %48 = iota : tile<1xi32>
    %49 = addi %47, %48 : tile<1xi32>
    %50 = reshape %arg3 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %51 = broadcast %50 : tile<1xptr<i32>> -> tile<1xptr<i32>>
    %52 = offset %51, %49 : tile<1xptr<i32>>, tile<1xi32> -> tile<1xptr<i32>>
    %53 = store_ptr_tko weak %52, %45 token=%43 : tile<1xptr<i32>>, tile<1xi32> -> token
    %54 = reshape %20 : tile<i32> -> tile<1xi32>
    %55 = broadcast %54 : tile<1xi32> -> tile<1xi32>
    %56 = reshape %2 : tile<i32> -> tile<1xi32>
    %57 = broadcast %56 : tile<1xi32> -> tile<1xi32>
    %58 = iota : tile<1xi32>
    %59 = addi %57, %58 : tile<1xi32>
    %60 = reshape %arg3 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %61 = broadcast %60 : tile<1xptr<i32>> -> tile<1xptr<i32>>
    %62 = offset %61, %59 : tile<1xptr<i32>>, tile<1xi32> -> tile<1xptr<i32>>
    %63 = store_ptr_tko weak %62, %55 token=%53 : tile<1xptr<i32>>, tile<1xi32> -> token
    return
  }
}
