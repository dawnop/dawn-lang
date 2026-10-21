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
    %9, %10 = load_ptr_tko weak %8 token=%0 : tile<ptr<i32>> -> tile<i32>, token
    %11 = constant <i32: 2> : tile<i32>
    %12 = offset %arg0, %11 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %13, %14 = load_ptr_tko weak %12 token=%0 : tile<ptr<i32>> -> tile<i32>, token
    %15 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %16 = offset %15, %1 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %17 = make_tensor_view %16, shape = [%5, %9], strides = [%9, %13] : tile<i32> -> tensor_view<?x?xf64, strides=[?, ?]>
    %18, %19 = get_tensor_shape %17 : tensor_view<?x?xf64, strides=[?, ?]> -> tile<i32>
    %20, %21 = get_tensor_shape %17 : tensor_view<?x?xf64, strides=[?, ?]> -> tile<i32>
    %22, %23, %24 = get_tile_block_id : tile<i32>
    %25 = constant <i32: 32> : tile<i32>
    %26 = muli %22, %25 : tile<i32>
    %27 = reshape %26 : tile<i32> -> tile<1xi32>
    %28 = broadcast %27 : tile<1xi32> -> tile<32xi32>
    %29 = iota : tile<32xi32>
    %30 = addi %28, %29 : tile<32xi32>
    %31 = reshape %21 : tile<i32> -> tile<1xi32>
    %32 = broadcast %31 : tile<1xi32> -> tile<32xi32>
    %33 = cmpi less_than %30, %32, signed : tile<32xi32> -> tile<32xi1>
    %34 = constant <f64: 0.0> : tile<32xf64>
    %35 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %36 = broadcast %35 : tile<1xptr<f64>> -> tile<32xptr<f64>>
    %37 = offset %36, %30 : tile<32xptr<f64>>, tile<32xi32> -> tile<32xptr<f64>>
    %38, %39 = load_ptr_tko weak %37, %33, %34 token=%0 : tile<32xptr<f64>>, tile<32xi1>, tile<32xf64> -> tile<32xf64>, token
    %40 = addf %38, %38 rounding<nearest_even> : tile<32xf64>
    %41 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %42 = broadcast %41 : tile<1xptr<f64>> -> tile<32xptr<f64>>
    %43 = offset %42, %30 : tile<32xptr<f64>>, tile<32xi32> -> tile<32xptr<f64>>
    %44 = store_ptr_tko weak %43, %40, %33 token=%0 : tile<32xptr<f64>>, tile<32xf64>, tile<32xi1> -> token
    %45 = reshape %18 : tile<i32> -> tile<1xi32>
    %46 = broadcast %45 : tile<1xi32> -> tile<1xi32>
    %47 = reshape %1 : tile<i32> -> tile<1xi32>
    %48 = broadcast %47 : tile<1xi32> -> tile<1xi32>
    %49 = iota : tile<1xi32>
    %50 = addi %48, %49 : tile<1xi32>
    %51 = reshape %arg3 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %52 = broadcast %51 : tile<1xptr<i32>> -> tile<1xptr<i32>>
    %53 = offset %52, %50 : tile<1xptr<i32>>, tile<1xi32> -> tile<1xptr<i32>>
    %54 = store_ptr_tko weak %53, %46 token=%44 : tile<1xptr<i32>>, tile<1xi32> -> token
    %55 = reshape %21 : tile<i32> -> tile<1xi32>
    %56 = broadcast %55 : tile<1xi32> -> tile<1xi32>
    %57 = reshape %2 : tile<i32> -> tile<1xi32>
    %58 = broadcast %57 : tile<1xi32> -> tile<1xi32>
    %59 = iota : tile<1xi32>
    %60 = addi %58, %59 : tile<1xi32>
    %61 = reshape %arg3 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %62 = broadcast %61 : tile<1xptr<i32>> -> tile<1xptr<i32>>
    %63 = offset %62, %60 : tile<1xptr<i32>>, tile<1xi32> -> tile<1xptr<i32>>
    %64 = store_ptr_tko weak %63, %56 token=%54 : tile<1xptr<i32>>, tile<1xi32> -> token
    return
  }
}
