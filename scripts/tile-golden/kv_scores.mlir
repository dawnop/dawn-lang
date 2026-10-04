cuda_tile.module @m {
  entry @kv_scores(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<i8>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 32> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1x1xi32>
    %7 = broadcast %6 : tile<1x1xi32> -> tile<64x32xi32>
    %8 = iota : tile<64xi32>
    %9 = reshape %8 : tile<64xi32> -> tile<64x1xi32>
    %10 = broadcast %9 : tile<64x1xi32> -> tile<64x32xi32>
    %11 = constant <i32: 0> : tile<64x32xi32>
    %12 = muli %10, %11 : tile<64x32xi32>
    %13 = addi %7, %12 : tile<64x32xi32>
    %14 = iota : tile<32xi32>
    %15 = reshape %14 : tile<32xi32> -> tile<1x32xi32>
    %16 = broadcast %15 : tile<1x32xi32> -> tile<64x32xi32>
    %17 = addi %13, %16 : tile<64x32xi32>
    %18 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %19 = broadcast %18 : tile<1x1xptr<f64>> -> tile<64x32xptr<f64>>
    %20 = offset %19, %17 : tile<64x32xptr<f64>>, tile<64x32xi32> -> tile<64x32xptr<f64>>
    %21, %22 = load_ptr_tko weak %20 token=%0 : tile<64x32xptr<f64>> -> tile<64x32xf64>, token
    %23 = constant <i32: 64> : tile<i32>
    %24 = muli %1, %23 : tile<i32>
    %25 = reshape %24 : tile<i32> -> tile<1x1xi32>
    %26 = broadcast %25 : tile<1x1xi32> -> tile<64x32xi32>
    %27 = iota : tile<64xi32>
    %28 = reshape %27 : tile<64xi32> -> tile<64x1xi32>
    %29 = broadcast %28 : tile<64x1xi32> -> tile<64x32xi32>
    %30 = addi %26, %29 : tile<64x32xi32>
    %31 = iota : tile<32xi32>
    %32 = reshape %31 : tile<32xi32> -> tile<1x32xi32>
    %33 = broadcast %32 : tile<1x32xi32> -> tile<64x32xi32>
    %34 = constant <i32: 0> : tile<64x32xi32>
    %35 = muli %33, %34 : tile<64x32xi32>
    %36 = addi %30, %35 : tile<64x32xi32>
    %37 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %38 = broadcast %37 : tile<1x1xptr<f64>> -> tile<64x32xptr<f64>>
    %39 = offset %38, %36 : tile<64x32xptr<f64>>, tile<64x32xi32> -> tile<64x32xptr<f64>>
    %40, %41 = load_ptr_tko weak %39 token=%22 : tile<64x32xptr<f64>> -> tile<64x32xf64>, token
    %42 = assume div_by<16>, %arg1 : tile<ptr<i8>>
    %43 = make_tensor_view %42, shape = [512, 32], strides = [32, 1] : tensor_view<512x32xi8, strides=[32, 1]>
    %44 = make_partition_view %43 : partition_view<tile=(64x32), padding_value = zero, tensor_view<512x32xi8, strides=[32, 1]>, dim_map=[0, 1]>
    %45, %46, %47 = get_tile_block_id : tile<i32>
    %48, %49, %50 = get_tile_block_id : tile<i32>
    %51, %52 = load_view_tko weak %44[%45, %49] token=%41 : partition_view<tile=(64x32), padding_value = zero, tensor_view<512x32xi8, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x32xi8>, token
    %53 = exti %51 unsigned : tile<64x32xi8> -> tile<64x32xi32>
    %54 = constant <i32: 128> : tile<64x32xi32>
    %55 = xori %53, %54 : tile<64x32xi32>
    %56 = constant <i32: 128> : tile<64x32xi32>
    %57 = subi %55, %56 : tile<64x32xi32>
    %58 = itof %57 signed rounding<nearest_even> : tile<64x32xi32> -> tile<64x32xf64>
    %59 = mulf %58, %40 rounding<nearest_even> : tile<64x32xf64>
    %60 = mulf %21, %59 rounding<nearest_even> : tile<64x32xf64>
    %61 = reduce %60 dim=1 identities=[0.0 : f64] : tile<64x32xf64> -> tile<64xf64> (%62: tile<f64>, %63: tile<f64>) {
      %64 = addf %62, %63 rounding<nearest_even> : tile<f64>
      yield %64 : tile<f64>
    }
    %65 = constant <f64: 0.17677669529663687> : tile<64xf64>
    %66 = mulf %61, %65 rounding<nearest_even> : tile<64xf64>
    %67 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %68 = make_tensor_view %67, shape = [512], strides = [1] : tensor_view<512xf64, strides=[1]>
    %69 = make_partition_view %68 : partition_view<tile=(64), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>
    %70 = store_view_tko weak %66, %69[%45] token=%52 : tile<64xf64>, partition_view<tile=(64), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
