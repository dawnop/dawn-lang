cuda_tile.module @m {
  entry @attr_round(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 768> : tile<i32>
    %7 = muli %1, %6 : tile<i32>
    %8, %9, %10 = get_num_tile_blocks : tile<i32>
    %11 = constant <i32: 128> : tile<i32>
    %12 = muli %8, %11 : tile<i32>
    %13 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %14 = make_tensor_view %13, shape = [%12], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %15 = make_partition_view %14 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %16, %17, %18 = get_tile_block_id : tile<i32>
    %19, %20 = load_view_tko weak %15[%16] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %21 = ftof %19 rounding<nearest_even> : tile<128xf64> -> tile<128xf32>
    %22 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %23 = make_tensor_view %22, shape = [%12], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %24 = make_partition_view %23 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %25, %26 = load_view_tko weak %24[%16] token=%20 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %27 = ftof %25 rounding<nearest_even> : tile<128xf64> -> tile<128xf32>
    %28 = addf %21, %27 rounding<negative_inf> : tile<128xf32>
    %29 = ftof %28 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %30 = reshape %7 : tile<i32> -> tile<1xi32>
    %31 = broadcast %30 : tile<1xi32> -> tile<128xi32>
    %32 = iota : tile<128xi32>
    %33 = addi %31, %32 : tile<128xi32>
    %34 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %35 = broadcast %34 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %36 = offset %35, %33 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %37 = store_ptr_tko weak %36, %29 token=%26 : tile<128xptr<f64>>, tile<128xf64> -> token
    %38 = constant <i32: 128> : tile<i32>
    %39 = addi %7, %38 : tile<i32>
    %40 = addf %21, %27 rounding<positive_inf> : tile<128xf32>
    %41 = ftof %40 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %42 = reshape %39 : tile<i32> -> tile<1xi32>
    %43 = broadcast %42 : tile<1xi32> -> tile<128xi32>
    %44 = iota : tile<128xi32>
    %45 = addi %43, %44 : tile<128xi32>
    %46 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %47 = broadcast %46 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %48 = offset %47, %45 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %49 = store_ptr_tko weak %48, %41 token=%37 : tile<128xptr<f64>>, tile<128xf64> -> token
    %50 = constant <i32: 256> : tile<i32>
    %51 = addi %7, %50 : tile<i32>
    %52 = mulf %21, %27 rounding<negative_inf> : tile<128xf32>
    %53 = ftof %52 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %54 = reshape %51 : tile<i32> -> tile<1xi32>
    %55 = broadcast %54 : tile<1xi32> -> tile<128xi32>
    %56 = iota : tile<128xi32>
    %57 = addi %55, %56 : tile<128xi32>
    %58 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %59 = broadcast %58 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %60 = offset %59, %57 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %61 = store_ptr_tko weak %60, %53 token=%49 : tile<128xptr<f64>>, tile<128xf64> -> token
    %62 = constant <i32: 384> : tile<i32>
    %63 = addi %7, %62 : tile<i32>
    %64 = mulf %21, %27 rounding<positive_inf> : tile<128xf32>
    %65 = ftof %64 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %66 = reshape %63 : tile<i32> -> tile<1xi32>
    %67 = broadcast %66 : tile<1xi32> -> tile<128xi32>
    %68 = iota : tile<128xi32>
    %69 = addi %67, %68 : tile<128xi32>
    %70 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %71 = broadcast %70 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %72 = offset %71, %69 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %73 = store_ptr_tko weak %72, %65 token=%61 : tile<128xptr<f64>>, tile<128xf64> -> token
    %74 = constant <i32: 512> : tile<i32>
    %75 = addi %7, %74 : tile<i32>
    %76 = divf %21, %27 rounding<negative_inf> : tile<128xf32>
    %77 = ftof %76 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %78 = reshape %75 : tile<i32> -> tile<1xi32>
    %79 = broadcast %78 : tile<1xi32> -> tile<128xi32>
    %80 = iota : tile<128xi32>
    %81 = addi %79, %80 : tile<128xi32>
    %82 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %83 = broadcast %82 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %84 = offset %83, %81 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %85 = store_ptr_tko weak %84, %77 token=%73 : tile<128xptr<f64>>, tile<128xf64> -> token
    %86 = constant <i32: 640> : tile<i32>
    %87 = addi %7, %86 : tile<i32>
    %88 = divf %21, %27 rounding<positive_inf> : tile<128xf32>
    %89 = ftof %88 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %90 = reshape %87 : tile<i32> -> tile<1xi32>
    %91 = broadcast %90 : tile<1xi32> -> tile<128xi32>
    %92 = iota : tile<128xi32>
    %93 = addi %91, %92 : tile<128xi32>
    %94 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %95 = broadcast %94 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %96 = offset %95, %93 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %97 = store_ptr_tko weak %96, %89 token=%85 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
